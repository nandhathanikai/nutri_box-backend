"""Add email verification columns to the users table.

Run once against the live database. Safe to re-run — uses IF NOT EXISTS.
Existing users are flagged as already-verified (defensible default: they
got in before the policy existed and we don't want to lock them out).
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from sqlalchemy import text
from app.database import engine

STATEMENTS = [
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS email_verified BOOLEAN NOT NULL DEFAULT FALSE;",
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS email_verification_token VARCHAR;",
    "CREATE INDEX IF NOT EXISTS ix_users_email_verification_token ON users (email_verification_token);",
    # Grandfather every existing account so we don't bounce known-good users
    # out of the app the moment we ship this. Truly fresh users get FALSE
    # because their row was created AFTER this UPDATE ran.
    "UPDATE users SET email_verified = TRUE WHERE email_verified = FALSE;",
]


def main():
    with engine.begin() as conn:
        for stmt in STATEMENTS:
            print(f"Running: {stmt[:80]}...")
            conn.execute(text(stmt))
    print("Done.")


if __name__ == "__main__":
    main()
