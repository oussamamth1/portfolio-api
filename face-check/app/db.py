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
ALTER TABLE suspects ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT now();
CREATE INDEX IF NOT EXISTS suspects_embedding_idx
    ON suspects USING hnsw (embedding vector_cosine_ops);

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
