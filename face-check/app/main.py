import hashlib
import hmac
import secrets
import threading
import time
from contextlib import asynccontextmanager
from pathlib import Path

import numpy as np
from fastapi import BackgroundTasks, Depends, FastAPI, File, Form, Header, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field

from . import auth, config, push
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


class OfficerSession:
    def __init__(self, officer_id: int, badge: str, token_hash: str):
        self.officer_id, self.badge, self.token_hash = officer_id, badge, token_hash

    @property
    def actor(self) -> str:
        return f"officer:{self.badge}"


def officer_session(request: Request, authorization: str | None = Header(None)) -> OfficerSession:
    """Officer signed in through the app: `Authorization: Bearer <token>`."""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "Please sign in")
    token_hash = auth.token_hash(authorization[7:].strip())
    with request.app.state.pool.connection() as conn:
        row = conn.execute(
            "SELECT o.id, o.badge FROM officer_sessions s JOIN officers o ON o.id = s.officer_id "
            "WHERE s.token_hash = %s AND s.expires_at > now() AND o.active",
            (token_hash,),
        ).fetchone()
    if not row:
        raise HTTPException(401, "Session expired or account disabled - please sign in again")
    return OfficerSession(row[0], row[1], token_hash)


def require_officer(request: Request, authorization: str | None = Header(None)) -> str:
    return officer_session(request, authorization).actor


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


WANTED_FILTERS = {
    "most": "most_wanted",
    "wanted": "wanted",
    "wanted_only": "wanted AND NOT most_wanted",
    "not": "NOT wanted",
}
SORTS = {
    "updated": "updated_at DESC",
    "newest": "id DESC",
    "name": "full_name ASC",
}


@app.get("/api/suspects")
def list_suspects(request: Request, q: str | None = None, wanted: str | None = None,
                  status: str | None = None, sort: str = "updated",
                  limit: int = 100, offset: int = 0, _: str = Depends(require_admin)):
    """List people. Filters: q (name/case/notes), wanted (most|wanted|wanted_only|not), status."""
    limit = max(1, min(limit, 500))
    where, params = [], []
    if q:
        where.append("(full_name ILIKE %s OR case_number ILIKE %s OR notes ILIKE %s)")
        params += [f"%{q}%"] * 3
    if wanted:
        if wanted not in WANTED_FILTERS:
            raise HTTPException(400, f"wanted must be one of {', '.join(WANTED_FILTERS)}")
        where.append(WANTED_FILTERS[wanted])
    if status:
        if status not in STATUSES:
            raise HTTPException(400, f"status must be one of {', '.join(STATUSES)}")
        where.append("status = %s")
        params.append(status)
    if sort not in SORTS:
        raise HTTPException(400, f"sort must be one of {', '.join(SORTS)}")
    where_sql = (" WHERE " + " AND ".join(where)) if where else ""
    with request.app.state.pool.connection() as conn:
        rows = conn.execute(
            "SELECT id, full_name, case_number, notes, created_at, wanted, status, updated_at, "
            f"most_wanted FROM suspects{where_sql} ORDER BY {SORTS[sort]} LIMIT %s OFFSET %s",
            (*params, limit, offset),
        ).fetchall()
        matching = conn.execute(f"SELECT count(*) FROM suspects{where_sql}", params).fetchone()[0]
        counts = conn.execute(
            "SELECT count(*), count(*) FILTER (WHERE most_wanted), "
            "count(*) FILTER (WHERE wanted AND NOT most_wanted), count(*) FILTER (WHERE NOT wanted) "
            "FROM suspects").fetchone()
    return {
        "total": counts[0],
        "matching": matching,
        "counts": {"all": counts[0], "most": counts[1], "wanted_only": counts[2], "not": counts[3]},
        "items": [
            {"id": r[0], "full_name": r[1], "case_number": r[2], "notes": r[3],
             "created_at": r[4].isoformat(), "wanted": r[5], "status": r[6],
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
    summary = ", ".join(f"{k}={v}" if k in ("wanted", "most_wanted", "status") else f"{k} edited"
                        for k, v in changes.items())
    audit(pool, actor, "update_suspect", summary, suspect_id)
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


LIVENESS = ("passed", "failed")


@app.post("/api/identify")
async def identify(request: Request, photo: UploadFile = File(...),
                   source: str = Form("photo"), liveness: str | None = Form(None),
                   actor: str = Depends(require_any)):
    """Compare the largest face in the photo with all suspects.

    The photo is processed in memory only and never stored.
    Results are *possible* matches for an officer to verify, never a decision.
    source: "photo" (taken/chosen photo) or "live" (live camera scan in the app).
    liveness: for live scans, whether the on-phone liveness check passed. It runs on the
    phone, so treat it as a hint for the audit trail, not as proof.
    """
    if source not in ("photo", "live"):
        raise HTTPException(400, "source must be photo or live")
    if liveness is not None and liveness not in LIVENESS:
        raise HTTPException(400, f"liveness must be one of {', '.join(LIVENESS)}")
    action = "identify_live" if source == "live" else "identify"
    note = f"; liveness={liveness}" if liveness else ""
    engine: FaceEngine = request.app.state.engine
    pool = request.app.state.pool
    data = await _read_image(photo)
    try:
        img = engine.decode(data)
    except ValueError as e:
        raise HTTPException(400, str(e))

    faces = engine.detect(img)
    if not faces:
        audit(pool, actor, action, "no_face" + note)
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
    audit(pool, actor, action, ("possible_match" if top else "no_match") + note,
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


# ---------- officer location and push token (mobile app) ----------

class LocationBody(BaseModel):
    lat: float = Field(..., ge=-90, le=90)
    lng: float = Field(..., ge=-180, le=180)
    accuracy: float | None = Field(None, ge=0)


@app.post("/api/officer/location")
def officer_location(request: Request, body: LocationBody, me: OfficerSession = Depends(officer_session)):
    """The app reports where this phone is, so it can receive alerts for its area."""
    with request.app.state.pool.connection() as conn:
        conn.execute(
            "UPDATE officer_sessions SET lat = %s, lng = %s, accuracy_m = %s, location_at = now() "
            "WHERE token_hash = %s",
            (body.lat, body.lng, body.accuracy, me.token_hash),
        )
    return {"ok": True}


class PushTokenBody(BaseModel):
    token: str = Field(..., min_length=10, max_length=4096)


@app.post("/api/officer/push-token")
def officer_push_token(request: Request, body: PushTokenBody, me: OfficerSession = Depends(officer_session)):
    with request.app.state.pool.connection() as conn:
        # A token belongs to one phone: drop it from any older session first.
        conn.execute("UPDATE officer_sessions SET push_token = NULL WHERE push_token = %s", (body.token,))
        conn.execute("UPDATE officer_sessions SET push_token = %s WHERE token_hash = %s",
                     (body.token, me.token_hash))
    return {"ok": True, "push_enabled": push.enabled()}


# ---------- alerts: wanted person found, tell nearby officers ----------

def _get_setting(conn, key: str, default: str) -> str:
    row = conn.execute("SELECT value FROM app_settings WHERE key = %s", (key,)).fetchone()
    return row[0] if row else default


def _radius_km(conn) -> float:
    return float(_get_setting(conn, "alert_radius_km", str(config.ALERT_DEFAULT_RADIUS_KM)))


# Great-circle distance in km between a row's (lat, lng) and the %(lat)s/%(lng)s parameters.
_KM_SQL = ("6371 * 2 * asin(least(1, sqrt(power(sin(radians({t}.lat - %(lat)s) / 2), 2) + "
           "cos(radians(%(lat)s)) * cos(radians({t}.lat)) * power(sin(radians({t}.lng - %(lng)s) / 2), 2))))")


def _photo_sig(alert_id: int, expires: int) -> str:
    msg = f"alert-photo:{alert_id}:{expires}".encode()
    return hmac.new(config.ADMIN_API_KEY.encode(), msg, hashlib.sha256).hexdigest()[:32]


def _public_base(request: Request) -> str:
    proto = request.headers.get("x-forwarded-proto", request.url.scheme)
    host = request.headers.get("x-forwarded-host", request.headers.get("host", request.url.netloc))
    return f"{proto}://{host}"


def _send_alert_pushes(pool, alert_id: int, tokens: list[str], title: str, body: str, image_url: str):
    dead = push.send(tokens, title, body, {"type": "alert", "alert_id": str(alert_id)}, image_url)
    sent = [t for t in tokens if t not in dead]
    with pool.connection() as conn:
        if dead:
            conn.execute("UPDATE officer_sessions SET push_token = NULL WHERE push_token = ANY(%s)", (dead,))
        if sent and push.enabled():
            conn.execute(
                "UPDATE alert_recipients r SET pushed = true FROM officer_sessions s "
                "WHERE r.alert_id = %s AND s.officer_id = r.officer_id AND s.push_token = ANY(%s)",
                (alert_id, sent),
            )


def _make_alert(conn, *, suspect_id: int, person, lat: float, lng: float, accuracy: float | None,
                similarity: float | None, photo: bytes, mime: str, officer_id: int | None,
                badge: str, camera_id: int | None = None, camera_name: str | None = None):
    """Store an alert and pick the on-duty officers within the radius (not the reporter).
    Returns (alert_id, radius_km, nearby officer count, push tokens)."""
    radius = _radius_km(conn)
    alert_id = conn.execute(
        "INSERT INTO alerts (suspect_id, full_name, case_number, most_wanted, officer_id, "
        "officer_badge, lat, lng, accuracy_m, similarity, photo, photo_mime, radius_km, camera_id, camera_name) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id",
        (suspect_id, person[0], person[1], person[3], officer_id, badge, lat, lng,
         accuracy, similarity, photo, mime, radius, camera_id, camera_name),
    ).fetchone()[0]

    rows = conn.execute(
        f"SELECT s.officer_id, s.push_token, {_KM_SQL.format(t='s')} AS km "
        "FROM officer_sessions s JOIN officers o ON o.id = s.officer_id "
        "WHERE o.active AND s.expires_at > now() AND s.lat IS NOT NULL "
        "AND s.location_at > now() - make_interval(mins => %(age)s::int) "
        "AND s.officer_id IS DISTINCT FROM %(me)s",
        {"lat": lat, "lng": lng, "age": config.LOCATION_MAX_AGE_MIN, "me": officer_id},
    ).fetchall()
    nearest: dict[int, float] = {}
    tokens: list[str] = []
    for oid, token, km in rows:
        if km is None or km > radius:
            continue
        nearest[oid] = min(km, nearest.get(oid, km))
        if token:
            tokens.append(token)
    for oid, km in nearest.items():
        conn.execute("INSERT INTO alert_recipients (alert_id, officer_id, distance_km) "
                     "VALUES (%s, %s, %s)", (alert_id, oid, km))
    conn.execute("DELETE FROM alerts WHERE created_at < now() - make_interval(days => %s::int)",
                 (config.ALERT_RETENTION_DAYS,))
    return alert_id, radius, len(nearest), tokens


def _queue_alert_push(request: Request, background: BackgroundTasks, alert_id: int, tokens: list[str],
                      person, reporter: str):
    if not tokens:
        return
    expires = int(time.time()) + 3600
    image_url = (f"{_public_base(request)}/api/alerts/{alert_id}/photo"
                 f"?e={expires}&sig={_photo_sig(alert_id, expires)}")
    title = ("MOST WANTED" if person[3] else "WANTED") + f" person spotted nearby: {person[0]}"
    body = f"Case {person[1]} - {reporter}. Tap to see the photo and location."
    background.add_task(_send_alert_pushes, request.app.state.pool, alert_id, tokens, title, body, image_url)


def _wanted_person(conn, suspect_id: int):
    person = conn.execute(
        "SELECT full_name, case_number, wanted, most_wanted FROM suspects WHERE id = %s",
        (suspect_id,)).fetchone()
    if not person:
        raise HTTPException(404, "Person not found")
    if not person[2]:
        raise HTTPException(400, "This person is not on the wanted list")
    return person


@app.post("/api/alerts")
async def create_alert(
    request: Request,
    background: BackgroundTasks,
    suspect_id: int = Form(...),
    lat: float = Form(..., ge=-90, le=90),
    lng: float = Form(..., ge=-180, le=180),
    accuracy: float | None = Form(None, ge=0),
    similarity: float | None = Form(None, ge=0, le=1),
    photo: UploadFile = File(...),
    me: OfficerSession = Depends(officer_session),
):
    """An officer found a wanted person: store the field photo and location, and
    notify every other on-duty officer within the alert radius."""
    data = await _read_image(photo)
    pool = request.app.state.pool
    with pool.connection() as conn:
        person = _wanted_person(conn, suspect_id)
        recent = conn.execute(
            "SELECT id FROM alerts WHERE suspect_id = %s AND officer_id = %s "
            "AND created_at > now() - make_interval(mins => %s::int) ORDER BY id DESC LIMIT 1",
            (suspect_id, me.officer_id, config.ALERT_DEDUPE_MIN)).fetchone()
        if recent:
            n = conn.execute("SELECT count(*) FROM alert_recipients WHERE alert_id = %s",
                             (recent[0],)).fetchone()[0]
            return {"id": recent[0], "duplicate": True, "recipients": n,
                    "push_enabled": push.enabled()}
        alert_id, radius, n, tokens = _make_alert(
            conn, suspect_id=suspect_id, person=person, lat=lat, lng=lng, accuracy=accuracy,
            similarity=similarity, photo=data, mime=photo.content_type or "image/jpeg",
            officer_id=me.officer_id, badge=me.badge)

    audit(pool, me.actor, "alert", f"alert #{alert_id}: {n} officers within {radius:g} km",
          suspect_id, similarity)
    _queue_alert_push(request, background, alert_id, tokens, person, f"reported by officer {me.badge}")
    return {"id": alert_id, "duplicate": False, "recipients": n, "radius_km": radius,
            "push_enabled": push.enabled()}


_ALERT_COLS = ("a.id, a.suspect_id, a.full_name, a.case_number, a.most_wanted, a.officer_badge, "
               "a.lat, a.lng, a.accuracy_m, a.similarity, a.created_at, a.radius_km, "
               "sp.status, sp.wanted, "
               "(SELECT count(*) FROM alert_recipients r2 WHERE r2.alert_id = a.id), a.camera_name")


def _alert_json(r, distance_km=None, mine=False) -> dict:
    return {
        "id": r[0], "suspect_id": r[1], "full_name": r[2], "case_number": r[3], "most_wanted": r[4],
        "officer_badge": r[5], "lat": r[6], "lng": r[7], "accuracy_m": r[8], "similarity": r[9],
        "created_at": r[10].isoformat(), "radius_km": r[11],
        "status": r[12], "still_wanted": bool(r[13]) if r[13] is not None else False,
        "recipients": r[14], "distance_km": distance_km, "sent_by_me": mine,
        "photo_url": f"/api/alerts/{r[0]}/photo",
        "reference_photo_url": f"/api/suspects/{r[1]}/photo" if r[1] else None,
        "camera_name": r[15],
    }


@app.get("/api/alerts")
def list_alerts(request: Request, days: int = 7, x_api_key: str | None = Header(None),
                authorization: str | None = Header(None)):
    """Officer: alerts sent to me or by me. Admin: all alerts."""
    days = max(1, min(days, 90))
    with request.app.state.pool.connection() as conn:
        if _key_ok(x_api_key, config.ADMIN_API_KEY):
            rows = conn.execute(
                f"SELECT {_ALERT_COLS} FROM alerts a LEFT JOIN suspects sp ON sp.id = a.suspect_id "
                "WHERE a.created_at > now() - make_interval(days => %s::int) ORDER BY a.id DESC LIMIT 500",
                (days,)).fetchall()
            return [_alert_json(r) for r in rows]
        me = officer_session(request, authorization)
        rows = conn.execute(
            f"SELECT {_ALERT_COLS}, r.distance_km, a.officer_id = %(me)s FROM alerts a "
            "LEFT JOIN suspects sp ON sp.id = a.suspect_id "
            "LEFT JOIN alert_recipients r ON r.alert_id = a.id AND r.officer_id = %(me)s "
            "WHERE (r.officer_id IS NOT NULL OR a.officer_id = %(me)s) "
            "AND a.created_at > now() - make_interval(days => %(days)s::int) ORDER BY a.id DESC LIMIT 200",
            {"me": me.officer_id, "days": days}).fetchall()
    return [_alert_json(r, r[16], r[17]) for r in rows]


def _officer_can_see(conn, alert_id: int, officer_id: int) -> bool:
    return conn.execute(
        "SELECT 1 FROM alerts a WHERE a.id = %s AND (a.officer_id = %s OR EXISTS "
        "(SELECT 1 FROM alert_recipients r WHERE r.alert_id = a.id AND r.officer_id = %s))",
        (alert_id, officer_id, officer_id)).fetchone() is not None


@app.get("/api/alerts/{alert_id}")
def get_alert(request: Request, alert_id: int, x_api_key: str | None = Header(None),
              authorization: str | None = Header(None)):
    with request.app.state.pool.connection() as conn:
        dist, mine = None, False
        if not _key_ok(x_api_key, config.ADMIN_API_KEY):
            me = officer_session(request, authorization)
            if not _officer_can_see(conn, alert_id, me.officer_id):
                raise HTTPException(404, "Not found")
            extra = conn.execute(
                "SELECT (SELECT distance_km FROM alert_recipients WHERE alert_id = %s AND officer_id = %s), "
                "(SELECT officer_id = %s FROM alerts WHERE id = %s)",
                (alert_id, me.officer_id, me.officer_id, alert_id)).fetchone()
            dist, mine = extra[0], bool(extra[1])
        row = conn.execute(
            f"SELECT {_ALERT_COLS} FROM alerts a LEFT JOIN suspects sp ON sp.id = a.suspect_id "
            "WHERE a.id = %s", (alert_id,)).fetchone()
    if not row:
        raise HTTPException(404, "Not found")
    return _alert_json(row, dist, mine)


@app.get("/api/alerts/{alert_id}/photo")
def alert_photo(request: Request, alert_id: int, e: int | None = None, sig: str | None = None,
                x_api_key: str | None = Header(None), authorization: str | None = Header(None)):
    """Field photo of an alert. Also reachable for one hour through the signed link put in
    the push notification, so Android can show the picture in the notification."""
    with request.app.state.pool.connection() as conn:
        signed = (e is not None and sig is not None and e > time.time()
                  and hmac.compare_digest(sig, _photo_sig(alert_id, e)))
        if not signed and not _key_ok(x_api_key, config.ADMIN_API_KEY):
            me = officer_session(request, authorization)
            if not _officer_can_see(conn, alert_id, me.officer_id):
                raise HTTPException(404, "Not found")
        row = conn.execute("SELECT photo, photo_mime FROM alerts WHERE id = %s", (alert_id,)).fetchone()
    if not row:
        raise HTTPException(404, "Not found")
    return Response(content=bytes(row[0]), media_type=row[1],
                    headers={"Cache-Control": "private, no-store"})


class AlertSettings(BaseModel):
    radius_km: float = Field(..., gt=0, le=500)


@app.get("/api/settings/alerts")
def get_alert_settings(request: Request, _: str = Depends(require_admin)):
    with request.app.state.pool.connection() as conn:
        radius = _radius_km(conn)
        on_duty = conn.execute(
            "SELECT count(DISTINCT s.officer_id), count(DISTINCT s.officer_id) FILTER (WHERE s.push_token IS NOT NULL) "
            "FROM officer_sessions s JOIN officers o ON o.id = s.officer_id WHERE o.active "
            "AND s.expires_at > now() AND s.location_at > now() - make_interval(mins => %s::int)",
            (config.LOCATION_MAX_AGE_MIN,)).fetchone()
    return {"radius_km": radius, "push_enabled": push.enabled(),
            "location_max_age_min": config.LOCATION_MAX_AGE_MIN,
            "officers_with_location": on_duty[0], "officers_with_push": on_duty[1],
            "retention_days": config.ALERT_RETENTION_DAYS}


@app.put("/api/settings/alerts")
def put_alert_settings(request: Request, body: AlertSettings, actor: str = Depends(require_admin)):
    pool = request.app.state.pool
    with pool.connection() as conn:
        conn.execute("INSERT INTO app_settings (key, value) VALUES ('alert_radius_km', %s) "
                     "ON CONFLICT (key) DO UPDATE SET value = excluded.value", (str(body.radius_km),))
    audit(pool, actor, "settings", f"alert radius = {body.radius_km:g} km")
    return get_alert_settings(request, actor)


# ---------- street cameras: registry (admin) ----------

CAMERA_COLS = ("c.id, c.name, c.area, c.lat, c.lng, c.active, c.threshold, c.created_at, c.last_seen_at, "
               "c.last_model, (SELECT count(*) FROM camera_matches m WHERE m.camera_id = c.id "
               "AND m.status = 'pending')")


def _camera_json(r) -> dict:
    online = r[8] is not None and (time.time() - r[8].timestamp()) < config.CAMERA_OFFLINE_AFTER_S
    return {"id": r[0], "name": r[1], "area": r[2], "lat": r[3], "lng": r[4], "active": r[5],
            "threshold": r[6], "effective_threshold": r[6] or config.CAMERA_MATCH_THRESHOLD,
            "created_at": r[7].isoformat(), "last_seen_at": r[8].isoformat() if r[8] else None,
            "online": online, "model": r[9], "pending_matches": r[10]}


class CameraCreate(BaseModel):
    name: str = Field(..., min_length=2, max_length=200)
    area: str | None = Field(None, max_length=200)
    lat: float = Field(..., ge=-90, le=90)
    lng: float = Field(..., ge=-180, le=180)
    threshold: float | None = Field(None, gt=0, lt=1)


class CameraUpdate(BaseModel):
    name: str | None = Field(None, min_length=2, max_length=200)
    area: str | None = Field(None, max_length=200)
    lat: float | None = Field(None, ge=-90, le=90)
    lng: float | None = Field(None, ge=-180, le=180)
    active: bool | None = None
    threshold: float | None = Field(None, gt=0, lt=1)   # null resets to the default


def _new_camera_key() -> tuple[str, str]:
    key = "cam_" + secrets.token_urlsafe(32)
    return key, auth.token_hash(key)


@app.get("/api/cameras")
def list_cameras(request: Request, _: str = Depends(require_admin)):
    with request.app.state.pool.connection() as conn:
        rows = conn.execute(f"SELECT {CAMERA_COLS} FROM cameras c ORDER BY c.name").fetchall()
    return {"default_threshold": config.CAMERA_MATCH_THRESHOLD, "model": config.MODEL_NAME,
            "items": [_camera_json(r) for r in rows]}


@app.post("/api/cameras")
def create_camera(request: Request, body: CameraCreate, actor: str = Depends(require_admin)):
    """Register a camera. The API key is returned only here: put it in the edge box config."""
    key, key_hash = _new_camera_key()
    pool = request.app.state.pool
    with pool.connection() as conn:
        cid = conn.execute(
            "INSERT INTO cameras (name, area, lat, lng, threshold, key_hash) VALUES (%s, %s, %s, %s, %s, %s) "
            "RETURNING id", (body.name.strip(), body.area, body.lat, body.lng, body.threshold, key_hash),
        ).fetchone()[0]
        row = conn.execute(f"SELECT {CAMERA_COLS} FROM cameras c WHERE c.id = %s", (cid,)).fetchone()
    audit(pool, actor, "create_camera", body.name)
    return {**_camera_json(row), "api_key": key}


@app.patch("/api/cameras/{camera_id}")
def update_camera(request: Request, camera_id: int, body: CameraUpdate, actor: str = Depends(require_admin)):
    changes = body.model_dump(exclude_unset=True)
    for k in ("name", "lat", "lng", "active"):
        if k in changes and changes[k] is None:
            raise HTTPException(400, f"{k} cannot be empty")
    if not changes:
        raise HTTPException(400, "Nothing to update")
    cols = ", ".join(f"{k} = %s" for k in changes)  # keys come from the model, not the client
    pool = request.app.state.pool
    with pool.connection() as conn:
        found = conn.execute(f"UPDATE cameras SET {cols} WHERE id = %s RETURNING name",
                             (*changes.values(), camera_id)).fetchone()
        if not found:
            raise HTTPException(404, "Not found")
        row = conn.execute(f"SELECT {CAMERA_COLS} FROM cameras c WHERE c.id = %s", (camera_id,)).fetchone()
    audit(pool, actor, "update_camera", f"{found[0]}: " + ", ".join(f"{k}={v}" for k, v in changes.items()))
    return _camera_json(row)


@app.post("/api/cameras/{camera_id}/key")
def rotate_camera_key(request: Request, camera_id: int, actor: str = Depends(require_admin)):
    """New API key for a camera; the old one stops working immediately."""
    key, key_hash = _new_camera_key()
    pool = request.app.state.pool
    with pool.connection() as conn:
        found = conn.execute("UPDATE cameras SET key_hash = %s WHERE id = %s RETURNING name",
                             (key_hash, camera_id)).fetchone()
    if not found:
        raise HTTPException(404, "Not found")
    audit(pool, actor, "rotate_camera_key", found[0])
    return {"id": camera_id, "api_key": key}


@app.delete("/api/cameras/{camera_id}")
def delete_camera(request: Request, camera_id: int, actor: str = Depends(require_admin)):
    pool = request.app.state.pool
    with pool.connection() as conn:
        found = conn.execute("DELETE FROM cameras WHERE id = %s RETURNING name", (camera_id,)).fetchone()
    if not found:
        raise HTTPException(404, "Not found")
    audit(pool, actor, "delete_camera", found[0])
    return {"deleted": camera_id}


# ---------- street cameras: edge box API (X-Camera-Key) ----------

class CameraAuth:
    def __init__(self, row):
        self.id, self.name, self.active, self.threshold, self.lat, self.lng = row

    @property
    def actor(self) -> str:
        return f"camera:{self.name}"


def camera_auth(request: Request, x_camera_key: str | None = Header(None)) -> CameraAuth:
    if not x_camera_key:
        raise HTTPException(401, "X-Camera-Key header is required")
    with request.app.state.pool.connection() as conn:
        row = conn.execute(
            "UPDATE cameras SET last_seen_at = now() WHERE key_hash = %s "
            "RETURNING id, name, active, threshold, lat, lng", (auth.token_hash(x_camera_key),)).fetchone()
    if not row:
        raise HTTPException(401, "Invalid camera key")
    return CameraAuth(row)


@app.get("/api/edge/config")
def edge_config(cam: CameraAuth = Depends(camera_auth)):
    """What the edge box needs: which face model to run (must match the server's) and the threshold."""
    return {"camera_id": cam.id, "name": cam.name, "active": cam.active, "model": config.MODEL_NAME,
            "threshold": cam.threshold or config.CAMERA_MATCH_THRESHOLD}


class HeartbeatBody(BaseModel):
    model: str | None = Field(None, max_length=50)


@app.post("/api/edge/heartbeat")
def edge_heartbeat(request: Request, body: HeartbeatBody, cam: CameraAuth = Depends(camera_auth)):
    if body.model:
        with request.app.state.pool.connection() as conn:
            conn.execute("UPDATE cameras SET last_model = %s WHERE id = %s", (body.model, cam.id))
    return {"ok": True, "active": cam.active}


class DetectionBody(BaseModel):
    embedding: list[float] = Field(..., min_length=512, max_length=512)
    model: str = Field(..., max_length=50)
    det_score: float | None = Field(None, ge=0, le=1)
    face_px: float | None = Field(None, ge=0)


@app.post("/api/edge/detections")
def edge_detection(request: Request, body: DetectionBody, cam: CameraAuth = Depends(camera_auth)):
    """One person seen by a camera (best frame of their track), as a face embedding.

    Only wanted people are compared. Nothing is stored unless the face matches; a match
    goes to the review queue (repeat sightings grouped, see CAMERA_GROUP_MIN).
    need_photo tells the edge box to upload its face crop for the reviewer.
    """
    if not cam.active:
        raise HTTPException(403, "Camera is disabled")
    if body.model != config.MODEL_NAME:
        raise HTTPException(409, f"Model mismatch: server uses {config.MODEL_NAME}, edge sent {body.model}")
    emb = np.asarray(body.embedding, dtype=np.float32)
    norm = float(np.linalg.norm(emb))
    if not np.isfinite(norm) or norm == 0:
        raise HTTPException(400, "Invalid embedding")
    emb /= norm
    threshold = cam.threshold or config.CAMERA_MATCH_THRESHOLD
    pool = request.app.state.pool
    with pool.connection() as conn:
        top = conn.execute(
            "SELECT id, 1 - (embedding <=> %s) AS sim FROM suspects WHERE wanted "
            "ORDER BY embedding <=> %s LIMIT 1", (emb, emb)).fetchone()
        if not top or float(top[1]) < threshold:
            return {"match": False}
        suspect_id, sim = top[0], round(float(top[1]), 3)
        # Group repeat sightings: into a pending review while the person keeps being seen,
        # and into a decided review for CAMERA_GROUP_MIN after the operator's decision.
        recent = conn.execute(
            "SELECT id, similarity, status, photo IS NOT NULL FROM camera_matches "
            "WHERE camera_id = %(cam)s AND suspect_id = %(sus)s AND CASE WHEN status = 'pending' "
            "THEN last_seen_at > now() - make_interval(mins => %(win)s::int) "
            "ELSE reviewed_at > now() - make_interval(mins => %(win)s::int) END "
            "ORDER BY id DESC LIMIT 1",
            {"cam": cam.id, "sus": suspect_id, "win": config.CAMERA_GROUP_MIN}).fetchone()
        if recent:
            better = sim > recent[1]
            conn.execute(
                "UPDATE camera_matches SET hits = hits + 1, last_seen_at = now(), "
                "similarity = GREATEST(similarity, %s) WHERE id = %s", (sim, recent[0]))
            pending = recent[2] == "pending"
            return {"match": True, "match_id": recent[0], "new": False,
                    "need_photo": pending and (better or not recent[3])}
        match_id = conn.execute(
            "INSERT INTO camera_matches (camera_id, suspect_id, similarity) VALUES (%s, %s, %s) RETURNING id",
            (cam.id, suspect_id, sim)).fetchone()[0]
        conn.execute("DELETE FROM camera_matches WHERE last_seen_at < now() - make_interval(days => %s::int)",
                     (config.ALERT_RETENTION_DAYS,))
    audit(pool, cam.actor, "camera_match", f"review #{match_id}", suspect_id, sim)
    return {"match": True, "match_id": match_id, "new": True, "need_photo": True}


@app.post("/api/edge/matches/{match_id}/photo")
async def edge_match_photo(request: Request, match_id: int, photo: UploadFile = File(...),
                           cam: CameraAuth = Depends(camera_auth)):
    """Face crop for a pending match, so the reviewer can compare it with the photo on file."""
    data = await _read_image(photo)
    with request.app.state.pool.connection() as conn:
        found = conn.execute(
            "UPDATE camera_matches SET photo = %s, photo_mime = %s "
            "WHERE id = %s AND camera_id = %s AND status = 'pending' RETURNING id",
            (data, photo.content_type or "image/jpeg", match_id, cam.id)).fetchone()
    if not found:
        raise HTTPException(404, "No pending match with this id for this camera")
    return {"ok": True}


# ---------- street cameras: live view ----------
# Only while an admin is watching: the edge box is asked for frames, the server keeps
# the newest one in memory (never in the database). Assumes one server process.

LIVE_REQUEST_S = 60        # a viewer must renew every minute or the edge box stops sending
LIVE_FRAME_MAX_AGE_S = 10  # older frames are not shown
_live_lock = threading.Lock()
_live_until: dict[int, float] = {}                   # camera id -> stop sending after
_live_frames: dict[int, tuple[bytes, float]] = {}    # camera id -> (jpeg, received at)


def _live_wanted(camera_id: int) -> bool:
    with _live_lock:
        return _live_until.get(camera_id, 0) > time.time()


@app.post("/api/cameras/{camera_id}/live")
def request_live_view(request: Request, camera_id: int, actor: str = Depends(require_admin)):
    """Start or keep alive a live view. Call again at least every minute while watching."""
    pool = request.app.state.pool
    with pool.connection() as conn:
        row = conn.execute("SELECT name FROM cameras WHERE id = %s", (camera_id,)).fetchone()
    if not row:
        raise HTTPException(404, "Not found")
    with _live_lock:
        was_on = _live_until.get(camera_id, 0) > time.time()
        _live_until[camera_id] = time.time() + LIVE_REQUEST_S
    if not was_on:
        audit(pool, actor, "live_view", row[0])
    return {"ok": True, "expires_in_s": LIVE_REQUEST_S}


@app.delete("/api/cameras/{camera_id}/live")
def stop_live_view(camera_id: int, _: str = Depends(require_admin)):
    with _live_lock:
        _live_until.pop(camera_id, None)
        _live_frames.pop(camera_id, None)
    return {"ok": True}


@app.get("/api/cameras/{camera_id}/live.jpg")
def live_frame(camera_id: int, _: str = Depends(require_admin)):
    with _live_lock:
        frame = _live_frames.get(camera_id)
    if not frame or time.time() - frame[1] > LIVE_FRAME_MAX_AGE_S:
        return Response(status_code=204)  # no fresh frame yet
    return Response(content=frame[0], media_type="image/jpeg",
                    headers={"Cache-Control": "no-store", "X-Frame-Age": f"{time.time() - frame[1]:.1f}"})


@app.get("/api/edge/live")
def edge_live_wanted(cam: CameraAuth = Depends(camera_auth)):
    """Edge box asks every few seconds whether someone is watching this camera."""
    return {"live": _live_wanted(cam.id)}


@app.post("/api/edge/live-frame")
async def edge_live_frame(photo: UploadFile = File(...), cam: CameraAuth = Depends(camera_auth)):
    if not _live_wanted(cam.id):
        return {"live": False}  # nobody watching: drop it
    data = await photo.read(2 * 1024 * 1024 + 1)
    if len(data) > 2 * 1024 * 1024:
        raise HTTPException(413, "Frame too large")
    with _live_lock:
        _live_frames[cam.id] = (data, time.time())
    return {"live": True}


# ---------- street cameras: review queue (admin / control room) ----------

MATCH_COLS = ("m.id, m.camera_id, c.name, c.area, c.lat, c.lng, m.suspect_id, s.full_name, s.case_number, "
              "s.most_wanted, s.wanted, s.status, m.similarity, m.hits, m.photo IS NOT NULL, m.status, "
              "m.reviewed_by, m.reviewed_at, m.alert_id, m.first_seen_at, m.last_seen_at")


def _match_json(r) -> dict:
    return {"id": r[0], "camera_id": r[1], "camera_name": r[2], "camera_area": r[3], "lat": r[4], "lng": r[5],
            "suspect_id": r[6], "full_name": r[7], "case_number": r[8], "most_wanted": r[9], "wanted": r[10],
            "case_status": r[11], "similarity": r[12], "hits": r[13], "has_photo": r[14], "status": r[15],
            "reviewed_by": r[16], "reviewed_at": r[17].isoformat() if r[17] else None, "alert_id": r[18],
            "first_seen_at": r[19].isoformat(), "last_seen_at": r[20].isoformat(),
            "photo_url": f"/api/camera-matches/{r[0]}/photo" if r[14] else None,
            "reference_photo_url": f"/api/suspects/{r[6]}/photo"}


@app.get("/api/camera-matches")
def list_camera_matches(request: Request, status: str = "pending", limit: int = 100,
                        _: str = Depends(require_admin)):
    if status not in ("pending", "confirmed", "rejected", "all"):
        raise HTTPException(400, "status must be pending, confirmed, rejected or all")
    limit = max(1, min(limit, 500))
    where, params = ("", []) if status == "all" else (" WHERE m.status = %s", [status])
    with request.app.state.pool.connection() as conn:
        rows = conn.execute(
            f"SELECT {MATCH_COLS} FROM camera_matches m JOIN cameras c ON c.id = m.camera_id "
            f"JOIN suspects s ON s.id = m.suspect_id{where} ORDER BY m.last_seen_at DESC LIMIT %s",
            (*params, limit)).fetchall()
        pending = conn.execute("SELECT count(*) FROM camera_matches WHERE status = 'pending'").fetchone()[0]
    return {"pending": pending, "items": [_match_json(r) for r in rows]}


@app.get("/api/camera-matches/{match_id}/photo")
def camera_match_photo(request: Request, match_id: int, _: str = Depends(require_admin)):
    with request.app.state.pool.connection() as conn:
        row = conn.execute("SELECT photo, photo_mime FROM camera_matches WHERE id = %s", (match_id,)).fetchone()
    if not row or row[0] is None:
        raise HTTPException(404, "No photo")
    return Response(content=bytes(row[0]), media_type=row[1], headers={"Cache-Control": "private, no-store"})


def _pending_match(conn, match_id: int):
    row = conn.execute(
        "SELECT m.status, m.suspect_id, m.camera_id, c.name, c.lat, c.lng, m.similarity, m.photo, m.photo_mime "
        "FROM camera_matches m JOIN cameras c ON c.id = m.camera_id WHERE m.id = %s FOR UPDATE OF m",
        (match_id,)).fetchone()
    if not row:
        raise HTTPException(404, "Not found")
    if row[0] != "pending":
        raise HTTPException(409, f"Already {row[0]}")
    return row


@app.post("/api/camera-matches/{match_id}/confirm")
def confirm_camera_match(request: Request, background: BackgroundTasks, match_id: int,
                         actor: str = Depends(require_admin)):
    """Operator confirms it is the wanted person: alert officers near the camera."""
    pool = request.app.state.pool
    with pool.connection() as conn:
        _, suspect_id, camera_id, cam_name, lat, lng, sim, photo, mime = _pending_match(conn, match_id)
        if photo is None:
            raise HTTPException(409, "The camera has not uploaded the face photo yet - wait a few seconds")
        person = _wanted_person(conn, suspect_id)
        alert_id, radius, n, tokens = _make_alert(
            conn, suspect_id=suspect_id, person=person, lat=lat, lng=lng, accuracy=None, similarity=sim,
            photo=bytes(photo), mime=mime or "image/jpeg", officer_id=None, badge=f"camera:{cam_name}",
            camera_id=camera_id, camera_name=cam_name)
        conn.execute("UPDATE camera_matches SET status = 'confirmed', reviewed_by = %s, reviewed_at = now(), "
                     "alert_id = %s WHERE id = %s", (actor, alert_id, match_id))
    audit(pool, actor, "confirm_camera_match",
          f"review #{match_id} -> alert #{alert_id}: {n} officers within {radius:g} km", suspect_id, sim)
    _queue_alert_push(request, background, alert_id, tokens, person, f"seen by camera {cam_name}")
    return {"id": match_id, "status": "confirmed", "alert_id": alert_id, "recipients": n,
            "radius_km": radius, "push_enabled": push.enabled()}


@app.post("/api/camera-matches/{match_id}/reject")
def reject_camera_match(request: Request, match_id: int, actor: str = Depends(require_admin)):
    """Operator says it is not the person. The camera photo is deleted."""
    pool = request.app.state.pool
    with pool.connection() as conn:
        _, suspect_id, _, _, _, _, sim, _, _ = _pending_match(conn, match_id)
        conn.execute("UPDATE camera_matches SET status = 'rejected', reviewed_by = %s, reviewed_at = now(), "
                     "photo = NULL, photo_mime = NULL WHERE id = %s", (actor, match_id))
    audit(pool, actor, "reject_camera_match", f"review #{match_id}", suspect_id, sim)
    return {"id": match_id, "status": "rejected"}


@app.get("/api/audit")
def audit_log(request: Request, limit: int = 200, suspect_id: int | None = None,
              _: str = Depends(require_admin)):
    """Audit entries, newest first; with suspect_id, only that person's history."""
    limit = max(1, min(limit, 1000))
    where, params = "", []
    if suspect_id is not None:
        where, params = " WHERE suspect_id = %s", [suspect_id]
    with request.app.state.pool.connection() as conn:
        rows = conn.execute(
            "SELECT id, actor, action, result, suspect_id, top_similarity, created_at "
            f"FROM audit_log{where} ORDER BY id DESC LIMIT %s", (*params, limit)).fetchall()
    return [
        {"id": r[0], "actor": r[1], "action": r[2], "result": r[3], "suspect_id": r[4],
         "top_similarity": r[5], "created_at": r[6].isoformat()}
        for r in rows
    ]
