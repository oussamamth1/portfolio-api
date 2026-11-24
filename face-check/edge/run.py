"""Face Check edge box.

Runs at a street site next to the cameras. For each camera it reads the video stream,
finds and tracks faces, and sends the server only the best face embedding of each
person who passes. Video and faces of people who do not match are never stored or sent
anywhere; the face crop is uploaded only when the server reports a match, for the
control room to review.

Run from the face-check folder (it reuses the server's face model code):

    python -m edge.run --config edge/config.json [--preview]
"""
import argparse
import collections
import json
import logging
import os
import signal
import sys
import threading
import time
from dataclasses import dataclass

import cv2
import numpy as np
import requests

from app.faces import MODEL_FILES, FaceEngine

from .tracker import Tracker, face_crop_jpeg, face_quality

log = logging.getLogger("edge")


@dataclass
class Detection:
    camera: "CameraWorker"
    embedding: np.ndarray
    crop: bytes
    det_score: float
    face_px: float
    attempts: int = 0


class Server:
    def __init__(self, base_url: str, timeout: float = 30):
        self.base = base_url.rstrip("/")
        self.timeout = timeout
        self.http = requests.Session()

    def call(self, method: str, path: str, key: str, **kw) -> requests.Response:
        return self.http.request(method, self.base + path, headers={"X-Camera-Key": key},
                                 timeout=self.timeout, **kw)


class LatestFrame(threading.Thread):
    """Reads a stream as fast as it comes and keeps only the newest frame, so a slow
    face pipeline never works on video that is seconds old."""

    def __init__(self, source, name: str, stop: threading.Event):
        super().__init__(daemon=True, name=f"read:{name}")
        self.source, self.name, self.stop = source, name, stop
        self.lock = threading.Lock()
        self.frame: np.ndarray | None = None
        self.frame_time = 0.0
        self.connected = False

    def run(self):
        while not self.stop.is_set():
            cap = open_capture(self.source)
            if not cap.isOpened():
                self.connected = False
                log.warning("[%s] cannot open %s - retrying in 5 s", self.name, _redact(self.source))
                self.stop.wait(5)
                continue
            self.connected = True
            log.info("[%s] stream opened", self.name)
            fails = 0
            while not self.stop.is_set():
                ok, frame = cap.read()
                if not ok:
                    fails += 1
                    if fails > 50:
                        break
                    time.sleep(0.02)
                    continue
                fails = 0
                with self.lock:
                    self.frame, self.frame_time = frame, time.time()
            cap.release()
            self.connected = False
            if not self.stop.is_set():
                log.warning("[%s] stream lost - reconnecting", self.name)
                self.stop.wait(2)

    def latest(self) -> tuple[np.ndarray | None, float]:
        with self.lock:
            return self.frame, self.frame_time


def open_capture(source) -> cv2.VideoCapture:
    """Webcam index or stream URL. On macOS a webcam goes straight to AVFoundation
    (otherwise OpenCV tries other drivers first and floods the log)."""
    if isinstance(source, int) and sys.platform == "darwin":
        return cv2.VideoCapture(source, cv2.CAP_AVFOUNDATION)
    return cv2.VideoCapture(source)


def request_webcam_access(sources: list) -> None:
    """macOS asks for camera permission only from the main thread: open each local
    webcam once here, before the camera threads start, so the prompt appears."""
    if sys.platform != "darwin":
        return
    for src in sources:
        if isinstance(src, int):
            cap = open_capture(src)
            ok = cap.isOpened() and cap.read()[0]
            cap.release()
            if not ok:
                log.error("Webcam %d not available. Allow camera access for the app running this "
                          "(System Settings > Privacy & Security > Camera), then start again.", src)


def _redact(source) -> str:
    """Hide passwords in rtsp://user:pass@host URLs when logging."""
    s = str(source)
    if "@" in s and "://" in s:
        scheme, rest = s.split("://", 1)
        return f"{scheme}://***@{rest.split('@', 1)[1]}"
    return s


class CameraWorker(threading.Thread):
    def __init__(self, cfg: dict, engine: FaceEngine, sender: "Sender", opts, stop: threading.Event):
        super().__init__(daemon=True, name=f"cam:{cfg['name']}")
        self.name_ = cfg["name"]
        self.key = cfg["key"]
        source = cfg["source"]
        self.source = int(source) if isinstance(source, str) and source.isdigit() else source
        # Camera mounted sideways / phone held upright: turn frames so faces are upright.
        self.rotate = {0: None, 90: cv2.ROTATE_90_CLOCKWISE, 180: cv2.ROTATE_180,
                       270: cv2.ROTATE_90_COUNTERCLOCKWISE}[int(cfg.get("rotate", 0)) % 360]
        self.engine, self.sender, self.opts, self.stop = engine, sender, opts, stop
        self.reader = LatestFrame(self.source, self.name_, stop)
        self.tracker = Tracker(send_after_s=opts.send_after)
        self.active = True
        self.preview: np.ndarray | None = None
        self.last_faces: list[tuple[np.ndarray, bool]] = []   # for the live view overlay
        self.stats = collections.Counter()

    def run(self):
        self.reader.start()
        interval = 1.0 / self.opts.fps
        last = 0.0
        while not self.stop.is_set():
            frame, t = self.reader.latest()
            if frame is None or t <= last or not self.active:
                self.stop.wait(0.05)
                continue
            last = t
            started = time.time()
            try:
                self.process(frame, t)
            except Exception:
                log.exception("[%s] frame processing failed", self.name_)
            self.stop.wait(max(0.0, interval - (time.time() - started)))

    def process(self, frame: np.ndarray, now: float):
        if self.rotate is not None:
            frame = cv2.rotate(frame, self.rotate)
        faces = self.engine.detector.detect(frame)
        self.stats["frames"] += 1
        self.last_faces = [(f.bbox, f.det_score >= self.opts.min_det_score and f.kps is not None
                            and float(f.bbox[2] - f.bbox[0]) >= self.opts.min_face_px) for f in faces]
        shown = frame.copy() if self.opts.preview else None
        for f in faces:
            width = float(f.bbox[2] - f.bbox[0])
            usable = f.det_score >= self.opts.min_det_score and width >= self.opts.min_face_px and f.kps is not None
            if shown is not None:
                color = (0, 200, 0) if usable else (0, 165, 255)
                x1, y1, x2, y2 = (int(v) for v in f.bbox)
                cv2.rectangle(shown, (x1, y1), (x2, y2), color, 2)
                cv2.putText(shown, f"{int(width)}px", (x1, max(15, y1 - 6)), cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1)
            if not usable:
                continue
            track = self.tracker.match(f.bbox, now)
            q = face_quality(frame, f.bbox, f.kps, f.det_score)
            if q > track.best_quality * 1.1:
                # Embedding is the expensive part: only for a clearly better face of this person.
                track.best_quality = q
                track.best_embedding = self.engine.recognizer.embed(frame, f.kps)
                track.best_crop = face_crop_jpeg(frame, f.bbox)
                track.best_det_score = f.det_score
                track.best_face_px = width
        for t in self.tracker.ready(now):
            self.stats["people"] += 1
            self.sender.submit(Detection(self, t.best_embedding, t.best_crop, t.best_det_score, t.best_face_px))
        if shown is not None:
            self.preview = shown


class Sender(threading.Thread):
    """Sends detections to the server; keeps them (up to a limit) while the network is down."""

    def __init__(self, server: Server, model: str, stop: threading.Event, max_queue: int = 500):
        super().__init__(daemon=True, name="sender")
        self.server, self.model, self.stop = server, model, stop
        self.queue: collections.deque[Detection] = collections.deque(maxlen=max_queue)
        self.cv = threading.Condition()

    def submit(self, d: Detection):
        with self.cv:
            if len(self.queue) == self.queue.maxlen:
                log.warning("offline queue full - dropping the oldest detection")
            self.queue.append(d)
            self.cv.notify()

    def run(self):
        backoff = 1.0
        while not self.stop.is_set():
            with self.cv:
                while not self.queue and not self.stop.is_set():
                    self.cv.wait(1)
                if self.stop.is_set():
                    return
                d = self.queue.popleft()
            try:
                self.send(d)
                backoff = 1.0
            except requests.RequestException as e:
                d.attempts += 1
                log.warning("server unreachable (%s) - %d detection(s) waiting", e.__class__.__name__,
                            len(self.queue) + 1)
                with self.cv:
                    self.queue.appendleft(d)
                self.stop.wait(backoff)
                backoff = min(60.0, backoff * 2)

    def send(self, d: Detection):
        cam = d.camera
        r = self.server.call("POST", "/api/edge/detections", cam.key, json={
            "embedding": [float(x) for x in d.embedding], "model": self.model,
            "det_score": round(float(d.det_score), 3), "face_px": round(d.face_px, 1)})
        if r.status_code >= 500:
            raise requests.ConnectionError(f"server error {r.status_code}")
        if r.status_code == 403:
            cam.active = False
            log.warning("[%s] camera is disabled on the server - pausing it", cam.name_)
            return
        if r.status_code != 200:
            log.error("[%s] detection refused: %s %s", cam.name_, r.status_code, r.text[:200])
            return
        res = r.json()
        if not res.get("match"):
            return
        cam.stats["matches"] += 1
        log.warning("[%s] POSSIBLE WANTED PERSON - review #%s (%s)", cam.name_, res["match_id"],
                    "new" if res.get("new") else "seen again")
        if res.get("need_photo") and d.crop:
            p = self.server.call("POST", f"/api/edge/matches/{res['match_id']}/photo", cam.key,
                                 files={"photo": ("face.jpg", d.crop, "image/jpeg")})
            if p.status_code != 200:
                log.error("[%s] photo upload refused: %s %s", cam.name_, p.status_code, p.text[:200])


def live_view_loop(server: Server, cam: CameraWorker, stop: threading.Event):
    """Sends frames only while an admin is watching this camera on /admin (about 2 per second,
    640 px, face boxes drawn). Otherwise just asks every 2 seconds whether someone is watching."""
    live = False
    while not stop.is_set():
        try:
            if not live:
                r = server.call("GET", "/api/edge/live", cam.key)
                live = r.status_code == 200 and r.json().get("live", False)
                if live:
                    log.info("[%s] live view opened on /admin - sending frames", cam.name_)
                if not live:
                    stop.wait(2)
                continue
            frame, _ = cam.reader.latest()
            if frame is None:
                stop.wait(0.5)
                continue
            if cam.rotate is not None:
                frame = cv2.rotate(frame, cam.rotate)
            else:
                frame = frame.copy()
            for bbox, usable in cam.last_faces:
                x1, y1, x2, y2 = (int(v) for v in bbox)
                cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 200, 0) if usable else (0, 165, 255),
                              max(2, frame.shape[1] // 300))
            s = 640 / max(frame.shape[:2])
            if s < 1:
                frame = cv2.resize(frame, (int(frame.shape[1] * s), int(frame.shape[0] * s)),
                                   interpolation=cv2.INTER_AREA)
            ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 70])
            if ok:
                r = server.call("POST", "/api/edge/live-frame", cam.key,
                                files={"photo": ("live.jpg", buf.tobytes(), "image/jpeg")})
                live = r.status_code == 200 and r.json().get("live", False)
                if not live:
                    log.info("[%s] live view closed", cam.name_)
            stop.wait(0.5)
        except requests.RequestException:
            live = False
            stop.wait(5)


def heartbeat_loop(server: Server, cameras: list[CameraWorker], model: str, stop: threading.Event):
    first = True
    while first or not stop.wait(60):
        first = False
        for cam in cameras:
            try:
                r = server.call("POST", "/api/edge/heartbeat", cam.key, json={"model": model})
                if r.status_code == 200:
                    was = cam.active
                    cam.active = bool(r.json().get("active", True))
                    if cam.active != was:
                        log.warning("[%s] camera %s on the server", cam.name_, "enabled" if cam.active else "disabled")
                log.info("[%s] %s, frames=%d people=%d matches=%d", cam.name_,
                         "stream ok" if cam.reader.connected else "NO STREAM",
                         cam.stats["frames"], cam.stats["people"], cam.stats["matches"])
            except requests.RequestException:
                log.warning("[%s] heartbeat failed (server unreachable)", cam.name_)


def main():
    p = argparse.ArgumentParser(description="Face Check edge box")
    p.add_argument("--config", default="edge/config.json")
    p.add_argument("--preview", action="store_true", help="show the video with face boxes (for setup)")
    args = p.parse_args()

    with open(args.config) as f:
        cfg = json.load(f)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    opts = argparse.Namespace(
        fps=float(cfg.get("fps", 5)),
        min_face_px=float(cfg.get("min_face_px", 80)),
        min_det_score=float(cfg.get("min_det_score", 0.6)),
        send_after=float(cfg.get("send_after_s", 3)),
        preview=args.preview,
    )
    server = Server(cfg["server"])
    if not cfg.get("cameras"):
        raise SystemExit("No cameras in the config")

    # Every camera must agree with the server on the face model, or embeddings are not comparable.
    model = None
    for cam in cfg["cameras"]:
        r = server.call("GET", "/api/edge/config", cam["key"])
        if r.status_code != 200:
            raise SystemExit(f"Camera {cam['name']!r}: server refused the key ({r.status_code} {r.text[:200]})")
        c = r.json()
        log.info("camera %r registered on the server as %r (threshold %.2f, %s)", cam["name"], c["name"],
                 c["threshold"], "active" if c["active"] else "DISABLED")
        model = model or c["model"]

    model_root = os.path.expanduser(cfg.get("model_root", "~/.insightface"))
    missing = [f for f in MODEL_FILES[model] if not os.path.exists(os.path.join(model_root, model, f))]
    if missing:
        raise SystemExit(f"Model {model} not found in {model_root}. Run: "
                         f"MODEL_ROOT={model_root} python download_models.py {model}")
    log.info("loading face model %s", model)
    engine = FaceEngine(model, model_root, det_size=int(cfg.get("det_size", 640)))

    stop = threading.Event()
    signal.signal(signal.SIGINT, lambda *_: stop.set())
    signal.signal(signal.SIGTERM, lambda *_: stop.set())

    sender = Sender(server, model, stop)
    sender.start()
    cameras = [CameraWorker(c, engine, sender, opts, stop) for c in cfg["cameras"]]
    request_webcam_access([cam.source for cam in cameras])
    for cam in cameras:
        cam.start()
    threading.Thread(target=heartbeat_loop, args=(server, cameras, model, stop), daemon=True).start()
    for cam in cameras:
        threading.Thread(target=live_view_loop, args=(Server(cfg["server"]), cam, stop), daemon=True,
                         name=f"live:{cam.name_}").start()
    log.info("running %d camera(s) at %.0f fps each - Ctrl+C to stop", len(cameras), opts.fps)

    while not stop.is_set():
        if args.preview:
            # OpenCV windows must be driven from the main thread.
            for cam in cameras:
                if cam.preview is not None:
                    cv2.imshow(cam.name_, cam.preview)
            if cv2.waitKey(30) & 0xFF in (27, ord("q")):
                stop.set()
        else:
            stop.wait(0.5)
    log.info("stopping")
    if args.preview:
        cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
