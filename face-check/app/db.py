import psycopg
from pgvector.psycopg import register_vector
from psycopg_pool import ConnectionPool

SCHEMA = """
CREATE TABLE IF NOT EXISTS suspects (
    id          SERIAL PRIMARY KEY,
    full_name   TEXT NOT NULL,
    case_number TEXT NOT NULL,
    notes       TEXT,
    photo       BYTEA NOT NULL,
    photo_mime  TEXT NOT NULL,
    embedding   vector(512) NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
ALTER TABLE suspects ADD COLUMN IF NOT EXISTS wanted BOOLEAN NOT NULL DEFAULT true;
ALTER TABLE suspects ADD COLUMN IF NOT EXISTS status TEXT NOT NULL DEFAULT 'open';
ALTER TABLE suspects ADD COLUMN IF NOT EXISTS most_wanted BOOLEAN NOT NULL DEFAULT false;
ALTER TABLE suspects ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT now();
CREATE INDEX IF NOT EXISTS suspects_embedding_idx
    ON suspects USING hnsw (embedding vector_cosine_ops);

CREATE TABLE IF NOT EXISTS officers (
    id            SERIAL PRIMARY KEY,
    badge         TEXT NOT NULL UNIQUE,
    full_name     TEXT NOT NULL,
    password_hash TEXT NOT NULL,
    active        BOOLEAN NOT NULL DEFAULT true,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_login_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS officer_sessions (
    token_hash  TEXT PRIMARY KEY,
    officer_id  INT NOT NULL REFERENCES officers(id) ON DELETE CASCADE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at  TIMESTAMPTZ NOT NULL
);
CREATE INDEX IF NOT EXISTS officer_sessions_officer_idx ON officer_sessions (officer_id);

-- Per phone: where the officer is and how to reach them with a push notification.
ALTER TABLE officer_sessions ADD COLUMN IF NOT EXISTS push_token TEXT;
ALTER TABLE officer_sessions ADD COLUMN IF NOT EXISTS lat DOUBLE PRECISION;
ALTER TABLE officer_sessions ADD COLUMN IF NOT EXISTS lng DOUBLE PRECISION;
ALTER TABLE officer_sessions ADD COLUMN IF NOT EXISTS accuracy_m REAL;
ALTER TABLE officer_sessions ADD COLUMN IF NOT EXISTS location_at TIMESTAMPTZ;

CREATE TABLE IF NOT EXISTS alerts (
    id          SERIAL PRIMARY KEY,
    suspect_id  INT REFERENCES suspects(id) ON DELETE SET NULL,
    full_name   TEXT NOT NULL,          -- copied, so the alert still reads right if the person is removed
    case_number TEXT NOT NULL,
    most_wanted BOOLEAN NOT NULL,
    officer_id  INT REFERENCES officers(id) ON DELETE SET NULL,
    officer_badge TEXT NOT NULL,
    lat         DOUBLE PRECISION NOT NULL,
    lng         DOUBLE PRECISION NOT NULL,
    accuracy_m  REAL,
    similarity  REAL,
    photo       BYTEA NOT NULL,         -- the photo taken in the field
    photo_mime  TEXT NOT NULL,
    radius_km   REAL NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS alerts_created_idx ON alerts (created_at DESC);

CREATE TABLE IF NOT EXISTS alert_recipients (
    alert_id    INT NOT NULL REFERENCES alerts(id) ON DELETE CASCADE,
    officer_id  INT NOT NULL REFERENCES officers(id) ON DELETE CASCADE,
    distance_km REAL,
    pushed      BOOLEAN NOT NULL DEFAULT false,
    PRIMARY KEY (alert_id, officer_id)
);

CREATE TABLE IF NOT EXISTS app_settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

-- Street cameras: an edge box on site sends face embeddings; matches wait for review.
CREATE TABLE IF NOT EXISTS cameras (
    id           SERIAL PRIMARY KEY,
    name         TEXT NOT NULL,
    area         TEXT,
    lat          DOUBLE PRECISION NOT NULL,
    lng          DOUBLE PRECISION NOT NULL,
    active       BOOLEAN NOT NULL DEFAULT true,
    threshold    REAL,                    -- NULL = server default for cameras
    key_hash     TEXT NOT NULL UNIQUE,    -- SHA-256 of the camera's API key
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_seen_at TIMESTAMPTZ,
    last_model   TEXT
);

ALTER TABLE alerts ADD COLUMN IF NOT EXISTS camera_id INT REFERENCES cameras(id) ON DELETE SET NULL;
ALTER TABLE alerts ADD COLUMN IF NOT EXISTS camera_name TEXT;

CREATE TABLE IF NOT EXISTS camera_matches (
    id            SERIAL PRIMARY KEY,
    camera_id     INT NOT NULL REFERENCES cameras(id) ON DELETE CASCADE,
    suspect_id    INT NOT NULL REFERENCES suspects(id) ON DELETE CASCADE,
    similarity    REAL NOT NULL,
    hits          INT NOT NULL DEFAULT 1,
    photo         BYTEA,                  -- face crop from the camera, uploaded after the match
    photo_mime    TEXT,
    status        TEXT NOT NULL DEFAULT 'pending',   -- pending | confirmed | rejected
    reviewed_by   TEXT,
    reviewed_at   TIMESTAMPTZ,
    alert_id      INT REFERENCES alerts(id) ON DELETE SET NULL,
    first_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_seen_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS camera_matches_status_idx ON camera_matches (status, last_seen_at DESC);

CREATE TABLE IF NOT EXISTS audit_log (
    id             BIGSERIAL PRIMARY KEY,
    actor          TEXT NOT NULL,
    action         TEXT NOT NULL,
    result         TEXT,
    suspect_id     INT,
    top_similarity REAL,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);
"""


def init_db(url: str) -> ConnectionPool:
    with psycopg.connect(url, autocommit=True) as conn:
        conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
        register_vector(conn)
        conn.execute(SCHEMA)
    return ConnectionPool(url, min_size=1, max_size=5, configure=register_vector, open=True)


def audit(pool: ConnectionPool, actor: str, action: str, result: str | None = None,
          suspect_id: int | None = None, top_similarity: float | None = None) -> None:
    with pool.connection() as conn:
        conn.execute(
            "INSERT INTO audit_log (actor, action, result, suspect_id, top_similarity) "
            "VALUES (%s, %s, %s, %s, %s)",
            (actor, action, result, suspect_id, top_similarity),
        )
