"""Add notification preference + created_at columns to the users table.

Idempotent — safe to run multiple times.
"""
from sqlalchemy import text
from app.database import engine


STATEMENTS = [
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS notif_delivery BOOLEAN DEFAULT TRUE NOT NULL",
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS notif_subscriptions BOOLEAN DEFAULT TRUE NOT NULL",
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS notif_offers BOOLEAN DEFAULT FALSE NOT NULL",
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ DEFAULT NOW()",
]


def run():
    with engine.begin() as conn:
        for stmt in STATEMENTS:
            print(f"-> {stmt}")
            conn.execute(text(stmt))
    print("OK - user notification + created_at columns ensured.")


if __name__ == "__main__":
    run()
