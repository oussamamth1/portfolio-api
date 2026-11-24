"""Keeps one track per person in front of a camera and remembers their best face.

A person walking past a camera appears in many frames. Sending every frame would flood
the server and send the same person many times, so each person is tracked across
frames (by box overlap) and only the best-quality face of the track is sent once.
"""
from dataclasses import dataclass, field

import cv2
import numpy as np


def iou(a: np.ndarray, b: np.ndarray) -> float:
    x1, y1 = max(a[0], b[0]), max(a[1], b[1])
    x2, y2 = min(a[2], b[2]), min(a[3], b[3])
    inter = max(0.0, x2 - x1) * max(0.0, y2 - y1)
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return float(inter / union) if union > 0 else 0.0


def face_quality(img: np.ndarray, bbox: np.ndarray, kps: np.ndarray | None, det_score: float) -> float:
    """Higher is better: bigger, sharper, more frontal, more confident faces."""
    w = float(bbox[2] - bbox[0])
    frontal = 1.0
    if kps is not None:
        le, re, nose = kps[0], kps[1], kps[2]
        span = float(re[0] - le[0])
        if span > 1:
            # Nose halfway between the eyes = looking at the camera
            r = float(nose[0] - le[0]) / span
            frontal = max(0.0, 1.0 - abs(r - 0.5) * 2)
    x1, y1, x2, y2 = (int(max(0, v)) for v in bbox)
    crop = img[y1:y2, x1:x2]
    sharp = 0.0
    if crop.size:
        gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
        sharp = min(1.0, cv2.Laplacian(gray, cv2.CV_64F).var() / 100.0)
    return w * det_score * (0.3 + 0.7 * frontal) * (0.3 + 0.7 * sharp)


def face_crop_jpeg(img: np.ndarray, bbox: np.ndarray, margin: float = 0.5, max_side: int = 400) -> bytes:
    """Face with some context around it, for the reviewer. Kept in memory only."""
    h, w = img.shape[:2]
    bw, bh = bbox[2] - bbox[0], bbox[3] - bbox[1]
    x1 = int(max(0, bbox[0] - bw * margin))
    y1 = int(max(0, bbox[1] - bh * margin))
    x2 = int(min(w, bbox[2] + bw * margin))
    y2 = int(min(h, bbox[3] + bh * margin))
    crop = img[y1:y2, x1:x2]
    s = max_side / max(crop.shape[:2])
    if s < 1:
        crop = cv2.resize(crop, (int(crop.shape[1] * s), int(crop.shape[0] * s)), interpolation=cv2.INTER_AREA)
    ok, buf = cv2.imencode(".jpg", crop, [cv2.IMWRITE_JPEG_QUALITY, 90])
    return buf.tobytes() if ok else b""


@dataclass
class Track:
    id: int
    bbox: np.ndarray
    first_seen: float
    last_seen: float
    best_quality: float = 0.0
    best_embedding: np.ndarray | None = None
    best_crop: bytes = b""
    best_det_score: float = 0.0
    best_face_px: float = 0.0
    sent: bool = False
    last_sent: float = 0.0
    hits: int = 1


@dataclass
class Tracker:
    iou_threshold: float = 0.25
    lost_after_s: float = 1.0     # person gone: send their best face
    send_after_s: float = 3.0     # person still there: send after this long anyway
    recheck_every_s: float = 10.0 # person stays in view: send their best face again this often (0 = never)
    tracks: dict[int, Track] = field(default_factory=dict)
    _next_id: int = 1

    def match(self, bbox: np.ndarray, now: float) -> Track:
        """Track for this face box: the overlapping existing one, or a new track."""
        best, best_iou = None, self.iou_threshold
        for t in self.tracks.values():
            if t.last_seen == now:
                continue  # already matched to another face in this frame
            v = iou(t.bbox, bbox)
            if v > best_iou:
                best, best_iou = t, v
        if best is None:
            best = Track(self._next_id, bbox, now, now)
            self.tracks[best.id] = best
            self._next_id += 1
        else:
            best.bbox, best.last_seen = bbox, now
            best.hits += 1
        return best

    def ready(self, now: float) -> list[Track]:
        """Tracks whose best face should be sent now. Finished tracks are removed.

        First check: when the person leaves, or after send_after_s if they stay.
        Re-check: every recheck_every_s while they stay, with the best face of that period.
        """
        out = []
        for tid in list(self.tracks):
            t = self.tracks[tid]
            gone = now - t.last_seen > self.lost_after_s
            if t.best_embedding is not None:
                first = not t.sent and (gone or now - t.first_seen >= self.send_after_s)
                again = (t.sent and not gone and self.recheck_every_s > 0
                         and now - t.last_sent >= self.recheck_every_s)
                if first or again:
                    out.append(_snapshot(t))
                    t.sent, t.last_sent = True, now
                    # Start collecting the best face of the next period.
                    t.best_quality, t.best_embedding, t.best_crop = 0.0, None, b""
            if gone:
                del self.tracks[tid]
        return out


def _snapshot(t: Track) -> Track:
    """Copy of what is sent, so resetting the track for the next period does not touch it."""
    return Track(t.id, t.bbox, t.first_seen, t.last_seen, t.best_quality, t.best_embedding, t.best_crop,
                 t.best_det_score, t.best_face_px, True, t.last_sent, t.hits)
