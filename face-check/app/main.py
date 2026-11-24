import secrets
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field

from . import auth, config
from .db import audit, init_db
from .faces import FaceEngine

STATIC = Path(__file__).parent / "static"

# Case status values; the admin page and the officer app show these labels.
STATUSES = ("open", "investigating", "arrested", "released", "closed")
login_limiter = auth.LoginLimiter()


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


def require_officer(request: Request, authorization: str | None = Header(None)) -> str:
    """Officer signed in through the app: `Authorization: Bearer <token>`."""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "Please sign in")
    with request.app.state.pool.connection() as conn:
        row = conn.execute(
            "SELECT o.badge FROM officer_sessions s JOIN officers o ON o.id = s.officer_id "
            "WHERE s.token_hash = %s AND s.expires_at > now() AND o.active",
            (auth.token_hash(authorization[7:].strip()),),
        ).fetchone()
    if not row:
        raise HTTPException(401, "Session expired or account disabled - please sign in again")
    return f"officer:{row[0]}"


def require_any(request: Request, x_api_key: str | None = Header(None),
                authorization: str | None = Header(None)) -> str:
    """Admin key or a signed-in officer (the admin page tests identify with its own key)."""
    if _key_ok(x_api_key, config.ADMIN_API_KEY):
        return "admin"
    return require_officer(request, authorization)


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
    wanted: bool = Form(True),
    most_wanted: bool = Form(False),
    status: str = Form("open"),
    photo: UploadFile = File(...),
    actor: str = Depends(require_admin),
):
    if status not in STATUSES:
        raise HTTPException(400, f"status must be one of {', '.join(STATUSES)}")
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
            "INSERT INTO suspects (full_name, case_number, notes, wanted, most_wanted, status, "
            "photo, photo_mime, embedding) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id",
            (full_name.strip(), case_number.strip(), notes, wanted, wanted and most_wanted, status, data,
             photo.content_type or "image/jpeg", engine.embedding(face)),
        ).fetchone()
    audit(pool, actor, "add_suspect", "ok", row[0])
    return {"id": row[0], "full_name": full_name, "case_number": case_number,
            "wanted": wanted, "most_wanted": wanted and most_wanted, "status": status}


@app.get("/api/suspects")
def list_suspects(request: Request, q: str | None = None, limit: int = 100, offset: int = 0,
                  _: str = Depends(require_admin)):
    limit = max(1, min(limit, 500))
    sql = ("SELECT id, full_name, case_number, notes, created_at, wanted, status, updated_at, "
           "most_wanted "
           "FROM suspects")
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
             "created_at": r[4].isoformat(), "wanted": r[5], "status": r[6],
         "most_wanted": r[7],
             "updated_at": r[7].isoformat(), "most_wanted": r[8]}
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


class SuspectUpdate(BaseModel):
    full_name: str | None = Field(None, min_length=2, max_length=200)
    case_number: str | None = Field(None, min_length=1, max_length=100)
    notes: str | None = Field(None, max_length=2000)
    wanted: bool | None = None
    most_wanted: bool | None = None
    status: str | None = None


@app.patch("/api/suspects/{suspect_id}")
def update_suspect(request: Request, suspect_id: int, body: SuspectUpdate,
                   actor: str = Depends(require_admin)):
    changes = body.model_dump(exclude_unset=True)
    if "status" in changes and changes["status"] not in STATUSES:
        raise HTTPException(400, f"status must be one of {', '.join(STATUSES)}")
    for k in ("full_name", "case_number", "wanted", "most_wanted", "status"):
        if k in changes and changes[k] is None:
            raise HTTPException(400, f"{k} cannot be empty")
    for k in ("full_name", "case_number"):
        if k in changes:
            changes[k] = changes[k].strip()
    if not changes:
        raise HTTPException(400, "Nothing to update")
    if changes.get("wanted") is False:
        changes["most_wanted"] = False  # not wanted means not on the most-wanted list either
    elif changes.get("most_wanted") is True:
        changes["wanted"] = True

    cols = ", ".join(f"{k} = %s" for k in changes)  # keys come from the model, not the client
    pool = request.app.state.pool
    with pool.connection() as conn:
        row = conn.execute(
            f"UPDATE suspects SET {cols}, updated_at = now() WHERE id = %s "
            "RETURNING id, full_name, case_number, notes, wanted, status, updated_at, most_wanted",
            (*changes.values(), suspect_id),
        ).fetchone()
    if not row:
        raise HTTPException(404, "Not found")
    summary = ", ".join(f"{k}={v}" for k, v in changes.items()
                        if k in ("wanted", "most_wanted", "status"))
    audit(pool, actor, "update_suspect", summary or "details", suspect_id)
    return {"id": row[0], "full_name": row[1], "case_number": row[2], "notes": row[3],
            "wanted": row[4], "status": row[5], "updated_at": row[6].isoformat(),
            "most_wanted": row[7]}


@app.delete("/api/suspects/{suspect_id}")
def delete_suspect(request: Request, suspect_id: int, actor: str = Depends(require_admin)):
    pool = request.app.state.pool
    with pool.connection() as conn:
        cur = conn.execute("DELETE FROM suspects WHERE id = %s", (suspect_id,))
    if cur.rowcount == 0:
        raise HTTPException(404, "Not found")
    audit(pool, actor, "delete_suspect", "ok", suspect_id)
    return {"deleted": suspect_id}


@app.get("/api/wanted")
def wanted_list(request: Request, q: str | None = None, actor: str = Depends(require_any)):
    """People currently wanted, most wanted first. For the officer app's Wanted list."""
    sql = ("SELECT id, full_name, case_number, notes, status, most_wanted, updated_at "
           "FROM suspects WHERE wanted")
    params: list = []
    if q:
        sql += " AND (full_name ILIKE %s OR case_number ILIKE %s)"
        params += [f"%{q}%", f"%{q}%"]
    sql += " ORDER BY most_wanted DESC, updated_at DESC LIMIT 500"
    with request.app.state.pool.connection() as conn:
        rows = conn.execute(sql, params).fetchall()
    return [
        {"id": r[0], "full_name": r[1], "case_number": r[2], "notes": r[3], "status": r[4],
         "most_wanted": r[5], "updated_at": r[6].isoformat(),
         "photo_url": f"/api/suspects/{r[0]}/photo"}
        for r in rows
    ]


@app.post("/api/identify")
async def identify(request: Request, photo: UploadFile = File(...),
                   actor: str = Depends(require_any)):
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
            "SELECT id, full_name, case_number, notes, 1 - (embedding <=> %s) AS sim, "
            "wanted, status, most_wanted "
            "FROM suspects ORDER BY embedding <=> %s LIMIT %s",
            (emb, emb, config.TOP_K),
        ).fetchall()

    matches = [
        {"id": r[0], "full_name": r[1], "case_number": r[2], "notes": r[3],
         "similarity": round(float(r[4]), 3), "wanted": r[5], "status": r[6],
         "most_wanted": r[7],
         "photo_url": f"/api/suspects/{r[0]}/photo"}
        for r in rows if float(r[4]) >= config.MATCH_THRESHOLD
    ]
    top = matches[0] if matches else None
    audit(pool, actor, "identify", "possible_match" if top else "no_match",
          top["id"] if top else None, top["similarity"] if top else None)
    return {"face_detected": True, "face_count": len(faces), "matches": matches,
            "threshold": config.MATCH_THRESHOLD}


# ---------- officer sign-in (mobile app) ----------

class LoginBody(BaseModel):
    badge: str = Field(..., min_length=1, max_length=64)
    password: str = Field(..., min_length=1, max_length=200)


@app.post("/api/officer/login")
def officer_login(request: Request, body: LoginBody):
    badge = body.badge.strip()
    pool = request.app.state.pool
    wait = login_limiter.locked_for(badge)
    if wait:
        raise HTTPException(429, f"Too many wrong passwords - try again in {wait // 60 + 1} min")
    with pool.connection() as conn:
        row = conn.execute("SELECT id, full_name, password_hash, active FROM officers WHERE badge = %s",
                           (badge,)).fetchone()
    if not auth.verify_password(body.password, row[2] if row else None):
        login_limiter.fail(badge)
        audit(pool, f"officer:{badge}", "login", "wrong_password")
        raise HTTPException(401, "Wrong badge number or password")
    if not row[3]:
        audit(pool, f"officer:{badge}", "login", "disabled")
        raise HTTPException(403, "This account is disabled - contact your administrator")
    login_limiter.reset(badge)
    token, token_hash = auth.new_token()
    with pool.connection() as conn:
        expires = conn.execute(
            "INSERT INTO officer_sessions (token_hash, officer_id, expires_at) "
            f"VALUES (%s, %s, now() + interval '{auth.SESSION_DAYS} days') RETURNING expires_at",
            (token_hash, row[0]),
        ).fetchone()[0]
        conn.execute("UPDATE officers SET last_login_at = now() WHERE id = %s", (row[0],))
        conn.execute("DELETE FROM officer_sessions WHERE expires_at < now()")
    audit(pool, f"officer:{badge}", "login", "ok")
    return {"token": token, "badge": badge, "full_name": row[1], "expires_at": expires.isoformat()}


@app.get("/api/officer/me")
def officer_me(request: Request, actor: str = Depends(require_officer)):
    badge = actor.split(":", 1)[1]
    with request.app.state.pool.connection() as conn:
        row = conn.execute("SELECT full_name FROM officers WHERE badge = %s", (badge,)).fetchone()
    return {"badge": badge, "full_name": row[0] if row else ""}


@app.post("/api/officer/logout")
def officer_logout(request: Request, authorization: str | None = Header(None),
                   actor: str = Depends(require_officer)):
    pool = request.app.state.pool
    with pool.connection() as conn:
        conn.execute("DELETE FROM officer_sessions WHERE token_hash = %s",
                     (auth.token_hash(authorization[7:].strip()),))
    audit(pool, actor, "logout", "ok")
    return {"ok": True}


# ---------- officer accounts (admin) ----------

class OfficerCreate(BaseModel):
    badge: str = Field(..., min_length=1, max_length=64)
    full_name: str = Field(..., min_length=2, max_length=200)
    password: str = Field(..., min_length=auth.MIN_PASSWORD_LEN, max_length=200)


class OfficerUpdate(BaseModel):
    full_name: str | None = Field(None, min_length=2, max_length=200)
    password: str | None = Field(None, min_length=auth.MIN_PASSWORD_LEN, max_length=200)
    active: bool | None = None


def _officer_json(r) -> dict:
    return {"id": r[0], "badge": r[1], "full_name": r[2], "active": r[3],
            "created_at": r[4].isoformat(), "last_login_at": r[5].isoformat() if r[5] else None,
            "sessions": r[6]}


_OFFICER_COLS = ("SELECT o.id, o.badge, o.full_name, o.active, o.created_at, o.last_login_at, "
                 "(SELECT count(*) FROM officer_sessions s WHERE s.officer_id = o.id "
                 "AND s.expires_at > now()) FROM officers o")


@app.get("/api/officers")
def list_officers(request: Request, _: str = Depends(require_admin)):
    with request.app.state.pool.connection() as conn:
        rows = conn.execute(_OFFICER_COLS + " ORDER BY o.badge").fetchall()
    return [_officer_json(r) for r in rows]


@app.post("/api/officers")
def create_officer(request: Request, body: OfficerCreate, actor: str = Depends(require_admin)):
    pool = request.app.state.pool
    badge = body.badge.strip()
    with pool.connection() as conn:
        if conn.execute("SELECT 1 FROM officers WHERE badge = %s", (badge,)).fetchone():
            raise HTTPException(409, f"Badge {badge} already has an account")
        oid = conn.execute(
            "INSERT INTO officers (badge, full_name, password_hash) VALUES (%s, %s, %s) RETURNING id",
            (badge, body.full_name.strip(), auth.hash_password(body.password)),
        ).fetchone()[0]
        row = conn.execute(_OFFICER_COLS + " WHERE o.id = %s", (oid,)).fetchone()
    audit(pool, actor, "create_officer", badge)
    return _officer_json(row)


@app.patch("/api/officers/{officer_id}")
def update_officer(request: Request, officer_id: int, body: OfficerUpdate,
                   actor: str = Depends(require_admin)):
    changes = body.model_dump(exclude_unset=True)
    if any(v is None for v in changes.values()):
        raise HTTPException(400, "Fields cannot be empty")
    if not changes:
        raise HTTPException(400, "Nothing to update")
    sets, params = [], []
    if "full_name" in changes:
        sets.append("full_name = %s"); params.append(changes["full_name"].strip())
    if "password" in changes:
        sets.append("password_hash = %s"); params.append(auth.hash_password(changes["password"]))
    if "active" in changes:
        sets.append("active = %s"); params.append(changes["active"])
    pool = request.app.state.pool
    with pool.connection() as conn:
        found = conn.execute(f"UPDATE officers SET {', '.join(sets)} WHERE id = %s RETURNING badge",
                             (*params, officer_id)).fetchone()
        if not found:
            raise HTTPException(404, "Not found")
        # A new password or a disabled account signs the officer out on every phone.
        if "password" in changes or changes.get("active") is False:
            conn.execute("DELETE FROM officer_sessions WHERE officer_id = %s", (officer_id,))
        row = conn.execute(_OFFICER_COLS + " WHERE o.id = %s", (officer_id,)).fetchone()
    what = ", ".join("password reset" if k == "password" else f"{k}={v}" for k, v in changes.items())
    audit(pool, actor, "update_officer", f"{found[0]}: {what}")
    return _officer_json(row)


@app.post("/api/officers/{officer_id}/signout")
def sign_out_officer(request: Request, officer_id: int, actor: str = Depends(require_admin)):
    pool = request.app.state.pool
    with pool.connection() as conn:
        row = conn.execute("SELECT badge FROM officers WHERE id = %s", (officer_id,)).fetchone()
        if not row:
            raise HTTPException(404, "Not found")
        conn.execute("DELETE FROM officer_sessions WHERE officer_id = %s", (officer_id,))
    audit(pool, actor, "signout_officer", row[0])
    return {"ok": True}


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
