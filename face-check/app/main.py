import secrets
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, Response

from . import config
from .db import audit, init_db
from .faces import FaceEngine

STATIC = Path(__file__).parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.engine = FaceEngine(config.MODEL_NAME, config.MODEL_ROOT)
    app.state.pool = init_db(config.DATABASE_URL)
    yield
    app.state.pool.close()


app = FastAPI(title="Face Check API", lifespan=lifespan)


# ---------- auth ----------

def _key_ok(given: str | None, expected: str) -> bool:
    return bool(given) and secrets.compare_digest(given, expected)


def require_admin(x_api_key: str | None = Header(None)) -> str:
    if not _key_ok(x_api_key, config.ADMIN_API_KEY):
        raise HTTPException(401, "Invalid admin key")
    return "admin"


def require_officer(x_api_key: str | None = Header(None),
                    x_officer_id: str | None = Header(None)) -> str:
    if not _key_ok(x_api_key, config.OFFICER_API_KEY):
        raise HTTPException(401, "Invalid officer key")
    if not x_officer_id or len(x_officer_id) > 64:
        raise HTTPException(400, "X-Officer-Id header is required")
    return f"officer:{x_officer_id}"


def require_any(x_api_key: str | None = Header(None),
                x_officer_id: str | None = Header(None)) -> str:
    if _key_ok(x_api_key, config.ADMIN_API_KEY):
        return "admin"
    return require_officer(x_api_key, x_officer_id)


async def _read_image(upload: UploadFile) -> bytes:
    data = await upload.read(config.MAX_UPLOAD_BYTES + 1)
    if len(data) > config.MAX_UPLOAD_BYTES:
        raise HTTPException(413, "Image too large (max 10 MB)")
    if not data:
        raise HTTPException(400, "Empty file")
    return data


# ---------- routes ----------

@app.get("/health")
def health():
    return {"ok": True}


@app.get("/admin", include_in_schema=False)
def admin_page():
    return FileResponse(STATIC / "admin.html")


@app.post("/api/suspects")
async def add_suspect(
    request: Request,
    full_name: str = Form(..., min_length=2, max_length=200),
    case_number: str = Form(..., min_length=1, max_length=100),
    notes: str | None = Form(None, max_length=2000),
    photo: UploadFile = File(...),
    actor: str = Depends(require_admin),
):
    engine: FaceEngine = request.app.state.engine
    data = await _read_image(photo)
    try:
        img = engine.decode(data)
    except ValueError as e:
        raise HTTPException(400, str(e))

    faces = engine.detect(img)
    if not faces:
        raise HTTPException(422, "No face found in the photo")
    if len(faces) > 1:
        raise HTTPException(422, f"{len(faces)} faces found - use a photo with exactly one person")
    face = faces[0]
    if face.det_score < config.MIN_DET_SCORE or engine.face_width(face) < config.MIN_ENROLL_FACE_PX:
        raise HTTPException(422, "Face too small or unclear - use a sharper, closer photo")

    pool = request.app.state.pool
    with pool.connection() as conn:
        row = conn.execute(
            "INSERT INTO suspects (full_name, case_number, notes, photo, photo_mime, embedding) "
            "VALUES (%s, %s, %s, %s, %s, %s) RETURNING id",
            (full_name.strip(), case_number.strip(), notes, data,
             photo.content_type or "image/jpeg", engine.embedding(face)),
        ).fetchone()
    audit(pool, actor, "add_suspect", "ok", row[0])
    return {"id": row[0], "full_name": full_name, "case_number": case_number}


@app.get("/api/suspects")
def list_suspects(request: Request, q: str | None = None, limit: int = 100, offset: int = 0,
                  _: str = Depends(require_admin)):
    limit = max(1, min(limit, 500))
    sql = "SELECT id, full_name, case_number, notes, created_at FROM suspects"
    params: list = []
    if q:
        sql += " WHERE full_name ILIKE %s OR case_number ILIKE %s"
        params += [f"%{q}%", f"%{q}%"]
    sql += " ORDER BY id DESC LIMIT %s OFFSET %s"
    params += [limit, offset]
    with request.app.state.pool.connection() as conn:
        rows = conn.execute(sql, params).fetchall()
        total = conn.execute("SELECT count(*) FROM suspects").fetchone()[0]
    return {
        "total": total,
        "items": [
            {"id": r[0], "full_name": r[1], "case_number": r[2], "notes": r[3],
             "created_at": r[4].isoformat()}
            for r in rows
        ],
    }


@app.get("/api/suspects/{suspect_id}/photo")
def suspect_photo(request: Request, suspect_id: int, _: str = Depends(require_any)):
    with request.app.state.pool.connection() as conn:
        row = conn.execute("SELECT photo, photo_mime FROM suspects WHERE id = %s",
                           (suspect_id,)).fetchone()
    if not row:
        raise HTTPException(404, "Not found")
    return Response(content=bytes(row[0]), media_type=row[1],
                    headers={"Cache-Control": "private, no-store"})


@app.delete("/api/suspects/{suspect_id}")
def delete_suspect(request: Request, suspect_id: int, actor: str = Depends(require_admin)):
    pool = request.app.state.pool
    with pool.connection() as conn:
        cur = conn.execute("DELETE FROM suspects WHERE id = %s", (suspect_id,))
    if cur.rowcount == 0:
        raise HTTPException(404, "Not found")
    audit(pool, actor, "delete_suspect", "ok", suspect_id)
    return {"deleted": suspect_id}


@app.post("/api/identify")
async def identify(request: Request, photo: UploadFile = File(...),
                   actor: str = Depends(require_officer)):
    """Compare the largest face in the photo with all suspects.

    The photo is processed in memory only and never stored.
    Results are *possible* matches for an officer to verify, never a decision.
    """
    engine: FaceEngine = request.app.state.engine
    pool = request.app.state.pool
    data = await _read_image(photo)
    try:
        img = engine.decode(data)
    except ValueError as e:
        raise HTTPException(400, str(e))

    faces = engine.detect(img)
    if not faces:
        audit(pool, actor, "identify", "no_face")
        return {"face_detected": False, "face_count": 0, "matches": [],
                "threshold": config.MATCH_THRESHOLD}

    emb = engine.embedding(faces[0])
    with pool.connection() as conn:
        rows = conn.execute(
            "SELECT id, full_name, case_number, notes, 1 - (embedding <=> %s) AS sim "
            "FROM suspects ORDER BY embedding <=> %s LIMIT %s",
            (emb, emb, config.TOP_K),
        ).fetchall()

    matches = [
        {"id": r[0], "full_name": r[1], "case_number": r[2], "notes": r[3],
         "similarity": round(float(r[4]), 3),
         "photo_url": f"/api/suspects/{r[0]}/photo"}
        for r in rows if float(r[4]) >= config.MATCH_THRESHOLD
    ]
    top = matches[0] if matches else None
    audit(pool, actor, "identify", "possible_match" if top else "no_match",
          top["id"] if top else None, top["similarity"] if top else None)
    return {"face_detected": True, "face_count": len(faces), "matches": matches,
            "threshold": config.MATCH_THRESHOLD}


@app.get("/api/audit")
def audit_log(request: Request, limit: int = 200, _: str = Depends(require_admin)):
    limit = max(1, min(limit, 1000))
    with request.app.state.pool.connection() as conn:
        rows = conn.execute(
            "SELECT id, actor, action, result, suspect_id, top_similarity, created_at "
            "FROM audit_log ORDER BY id DESC LIMIT %s", (limit,)).fetchall()
    return [
        {"id": r[0], "actor": r[1], "action": r[2], "result": r[3], "suspect_id": r[4],
         "top_similarity": r[5], "created_at": r[6].isoformat()}
        for r in rows
    ]
