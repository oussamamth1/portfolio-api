"""Face detection (SCRFD) + recognition (ArcFace) running directly on onnxruntime.

Uses the InsightFace model files without the `insightface` Python package, which pulls in
scipy / scikit-image / albumentations and does not fit in a 512 MB instance.
"""
import gc
from pathlib import Path

import cv2
import numpy as np
import onnx
import onnxruntime as ort

# Detection + recognition model files inside each InsightFace model pack
MODEL_FILES = {
    "buffalo_s": ("det_500m.onnx", "w600k_mbf.onnx"),
    "buffalo_l": ("det_10g.onnx", "w600k_r50.onnx"),
}

# Reference landmark positions for a 112x112 aligned ArcFace crop
ARCFACE_DST = np.array(
    [[38.2946, 51.6963], [73.5318, 51.5014], [56.0252, 71.7366],
     [41.5493, 92.3655], [70.7299, 92.2041]], dtype=np.float32)


class Face:
    __slots__ = ("bbox", "det_score", "kps", "normed_embedding")

    def __init__(self, bbox, det_score, kps):
        self.bbox = bbox
        self.det_score = float(det_score)
        self.kps = kps
        self.normed_embedding = None


def _session(path: Path) -> ort.InferenceSession:
    opts = ort.SessionOptions()
    opts.enable_cpu_mem_arena = False  # keep memory low on small instances
    opts.intra_op_num_threads = 1
    return ort.InferenceSession(str(path), sess_options=opts, providers=["CPUExecutionProvider"])


def _nms(dets: np.ndarray, thresh: float) -> list[int]:
    x1, y1, x2, y2, scores = dets[:, 0], dets[:, 1], dets[:, 2], dets[:, 3], dets[:, 4]
    areas = (x2 - x1 + 1) * (y2 - y1 + 1)
    order = scores.argsort()[::-1]
    keep = []
    while order.size > 0:
        i = order[0]
        keep.append(int(i))
        xx1 = np.maximum(x1[i], x1[order[1:]])
        yy1 = np.maximum(y1[i], y1[order[1:]])
        xx2 = np.minimum(x2[i], x2[order[1:]])
        yy2 = np.minimum(y2[i], y2[order[1:]])
        w = np.maximum(0.0, xx2 - xx1 + 1)
        h = np.maximum(0.0, yy2 - yy1 + 1)
        ovr = (w * h) / (areas[i] + areas[order[1:]] - w * h)
        order = order[np.where(ovr <= thresh)[0] + 1]
    return keep


def _similarity_transform(src: np.ndarray, dst: np.ndarray) -> np.ndarray:
    """Umeyama least-squares similarity transform (same as skimage SimilarityTransform)."""
    n = src.shape[0]
    src_mean, dst_mean = src.mean(0), dst.mean(0)
    src_c, dst_c = src - src_mean, dst - dst_mean
    A = dst_c.T @ src_c / n
    d = np.ones(2)
    if np.linalg.det(A) < 0:
        d[1] = -1
    U, S, Vt = np.linalg.svd(A)
    T = np.eye(3)
    T[:2, :2] = U @ np.diag(d) @ Vt
    scale = 1.0 / src_c.var(0).sum() * (S @ d)
    T[:2, 2] = dst_mean - scale * (T[:2, :2] @ src_mean)
    T[:2, :2] *= scale
    return T[:2]


class SCRFD:
    def __init__(self, path: Path, input_size: int = 640, thresh: float = 0.5, nms: float = 0.4):
        self.session = _session(path)
        self.input_name = self.session.get_inputs()[0].name
        self.output_names = [o.name for o in self.session.get_outputs()]
        n = len(self.output_names)
        if n not in (6, 9, 10, 15):
            raise RuntimeError(f"Unexpected SCRFD output count: {n}")
        self.fmc = 3 if n in (6, 9) else 5
        self.strides = [8, 16, 32] if self.fmc == 3 else [8, 16, 32, 64, 128]
        self.num_anchors = 2 if n in (6, 9) else 1
        self.use_kps = n in (9, 15)
        self.input_size = input_size
        self.thresh = thresh
        self.nms_thresh = nms
        self._centers: dict = {}

    def _anchor_centers(self, h: int, w: int, stride: int) -> np.ndarray:
        key = (h, w, stride)
        if key not in self._centers:
            c = np.stack(np.mgrid[:h, :w][::-1], axis=-1).astype(np.float32)
            c = (c * stride).reshape(-1, 2)
            if self.num_anchors > 1:
                c = np.stack([c] * self.num_anchors, axis=1).reshape(-1, 2)
            self._centers[key] = c
        return self._centers[key]

    def detect(self, img: np.ndarray) -> list[Face]:
        size = self.input_size
        h, w = img.shape[:2]
        scale = min(size / h, size / w)
        nh, nw = int(h * scale), int(w * scale)
        canvas = np.zeros((size, size, 3), dtype=np.uint8)
        canvas[:nh, :nw] = cv2.resize(img, (nw, nh))
        blob = cv2.dnn.blobFromImage(canvas, 1.0 / 128.0, (size, size), (127.5, 127.5, 127.5), swapRB=True)
        outs = self.session.run(self.output_names, {self.input_name: blob})
        outs = [o[0] if o.ndim == 3 else o for o in outs]

        scores_l, boxes_l, kps_l = [], [], []
        for i, stride in enumerate(self.strides):
            scores = outs[i].reshape(-1)
            bbox_d = outs[i + self.fmc] * stride
            centers = self._anchor_centers(size // stride, size // stride, stride)
            pos = np.where(scores >= self.thresh)[0]
            if pos.size == 0:
                continue
            c = centers[pos]
            d = bbox_d[pos]
            boxes_l.append(np.stack([c[:, 0] - d[:, 0], c[:, 1] - d[:, 1],
                                     c[:, 0] + d[:, 2], c[:, 1] + d[:, 3]], axis=-1))
            scores_l.append(scores[pos])
            if self.use_kps:
                k = outs[i + self.fmc * 2][pos] * stride
                kps = np.stack([c[:, j % 2] + k[:, j] for j in range(10)], axis=-1)
                kps_l.append(kps.reshape(-1, 5, 2))

        if not scores_l:
            return []
        scores = np.concatenate(scores_l)
        boxes = np.concatenate(boxes_l) / scale
        kps = np.concatenate(kps_l) / scale if self.use_kps else None
        dets = np.hstack([boxes, scores[:, None]]).astype(np.float32)
        keep = _nms(dets, self.nms_thresh)
        return [Face(dets[i, :4], dets[i, 4], kps[i] if kps is not None else None) for i in keep]


class ArcFace:
    def __init__(self, path: Path):
        # Same rule as insightface: models with built-in normalization take raw pixels
        model = onnx.load(str(path))
        names = [node.name for node in model.graph.node[:8]]
        has_sub = any(n.startswith("Sub") or n.startswith("_minus") for n in names)
        has_mul = any(n.startswith("Mul") or n.startswith("_mul") for n in names)
        self.mean, self.std = (0.0, 1.0) if (has_sub and has_mul) else (127.5, 127.5)
        del model
        gc.collect()
        self.session = _session(path)
        self.input_name = self.session.get_inputs()[0].name

    def embed(self, img: np.ndarray, kps: np.ndarray) -> np.ndarray:
        M = _similarity_transform(kps.astype(np.float64), ARCFACE_DST.astype(np.float64))
        crop = cv2.warpAffine(img, M, (112, 112), borderValue=0.0)
        blob = cv2.dnn.blobFromImage(crop, 1.0 / self.std, (112, 112),
                                     (self.mean, self.mean, self.mean), swapRB=True)
        emb = self.session.run(None, {self.input_name: blob})[0].reshape(-1)
        return (emb / np.linalg.norm(emb)).astype(np.float32)


class NoFaceError(ValueError):
    pass


class FaceEngine:
    def __init__(self, model_name: str, root: str, det_size: int = 640):
        if model_name not in MODEL_FILES:
            raise RuntimeError(f"Unknown MODEL_NAME {model_name!r}, use one of {list(MODEL_FILES)}")
        det_file, rec_file = MODEL_FILES[model_name]
        base = Path(root) / model_name
        self.detector = SCRFD(base / det_file, input_size=det_size)
        self.recognizer = ArcFace(base / rec_file)

    @staticmethod
    def decode(data: bytes) -> np.ndarray:
        img = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
        if img is None:
            raise ValueError("File is not a valid image")
        # Very large photos only cost memory; faces are still detectable at 1600px
        h, w = img.shape[:2]
        if max(h, w) > 1600:
            s = 1600 / max(h, w)
            img = cv2.resize(img, (int(w * s), int(h * s)), interpolation=cv2.INTER_AREA)
        return img

    def detect(self, img: np.ndarray) -> list[Face]:
        faces = self.detector.detect(img)
        faces.sort(key=lambda f: (f.bbox[2] - f.bbox[0]) * (f.bbox[3] - f.bbox[1]), reverse=True)
        for f in faces[:1]:  # only the largest face is ever used
            f.normed_embedding = self.recognizer.embed(img, f.kps)
        return faces

    @staticmethod
    def face_width(face: Face) -> float:
        return float(face.bbox[2] - face.bbox[0])

    @staticmethod
    def embedding(face: Face) -> np.ndarray:
        return face.normed_embedding
