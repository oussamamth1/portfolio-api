import cv2
import numpy as np
from insightface.app import FaceAnalysis


class NoFaceError(ValueError):
    pass


class FaceEngine:
    """Face detection (SCRFD) + recognition (ArcFace, 512-d normalized embeddings)."""

    def __init__(self, model_name: str, root: str, det_size: int = 640):
        self.app = FaceAnalysis(
            name=model_name,
            root=root,
            allowed_modules=["detection", "recognition"],
            providers=["CPUExecutionProvider"],
        )
        self.app.prepare(ctx_id=-1, det_size=(det_size, det_size))

    @staticmethod
    def decode(data: bytes) -> np.ndarray:
        img = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
        if img is None:
            raise ValueError("File is not a valid image")
        return img

    def detect(self, img: np.ndarray):
        faces = self.app.get(img)
        # Largest face first
        faces.sort(key=lambda f: (f.bbox[2] - f.bbox[0]) * (f.bbox[3] - f.bbox[1]), reverse=True)
        return faces

    @staticmethod
    def face_width(face) -> float:
        return float(face.bbox[2] - face.bbox[0])

    @staticmethod
    def embedding(face) -> np.ndarray:
        return face.normed_embedding.astype(np.float32)
