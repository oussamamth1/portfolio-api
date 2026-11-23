import os


def _required(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


DATABASE_URL = _required("DATABASE_URL")
ADMIN_API_KEY = _required("ADMIN_API_KEY")
OFFICER_API_KEY = _required("OFFICER_API_KEY")

# Cosine similarity (0..1) above which a suspect is shown as a *possible* match.
# ArcFace: same person is usually > 0.5, different people usually < 0.3.
# Calibrate this with real photos before any real use.
MATCH_THRESHOLD = float(os.environ.get("MATCH_THRESHOLD", "0.45"))
TOP_K = int(os.environ.get("TOP_K", "3"))

MODEL_NAME = os.environ.get("MODEL_NAME", "buffalo_l")
MODEL_ROOT = os.environ.get("MODEL_ROOT", os.path.expanduser("~/.insightface"))

MAX_UPLOAD_BYTES = 10 * 1024 * 1024
MIN_ENROLL_FACE_PX = 80
MIN_DET_SCORE = 0.6
