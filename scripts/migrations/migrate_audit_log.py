"""Create the audit_logs table.

Run once against the live database. Safe to re-run — uses IF NOT EXISTS.
This table is append-only — there is intentionally no FK to users so
deleting a customer never cascades away the row that records the deletion.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from sqlalchemy import text
from app.database import engine

STATEMENTS = [
    """
    CREATE TABLE IF NOT EXISTS audit_logs (
        id           SERIAL PRIMARY KEY,
        actor_id     INTEGER,
        actor_email  VARCHAR,
        action       VARCHAR NOT NULL,
        target_type  VARCHAR,
        target_id    VARCHAR,
        details      JSONB,
        created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );
    """,
    "CREATE INDEX IF NOT EXISTS ix_audit_logs_actor_id ON audit_logs (actor_id);",
    "CREATE INDEX IF NOT EXISTS ix_audit_logs_action ON audit_logs (action);",
    "CREATE INDEX IF NOT EXISTS ix_audit_logs_target_id ON audit_logs (target_id);",
    "CREATE INDEX IF NOT EXISTS ix_audit_logs_created_at ON audit_logs (created_at);",
]


def main():
    with engine.begin() as conn:
        for stmt in STATEMENTS:
            print(f"Running: {stmt.strip()[:80]}...")
            conn.execute(text(stmt))
    print("Done.")


if __name__ == "__main__":
    main()
