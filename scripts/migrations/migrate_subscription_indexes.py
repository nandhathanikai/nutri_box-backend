"""Add performance + idempotency constraints to subscriptions table.

Run once against the live database. Safe to re-run — uses IF NOT EXISTS.

- Indexes on customer_id and menu_id for join/filter performance.
- UNIQUE constraint on razorpay_order_id for payment idempotency at the DB
  level (defence in depth — the /verify and /webhook handlers also check).
"""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from sqlalchemy import text
from app.database import engine


STATEMENTS = [
    "CREATE INDEX IF NOT EXISTS ix_subscriptions_customer_id ON subscriptions (customer_id);",
    "CREATE INDEX IF NOT EXISTS ix_subscriptions_menu_id ON subscriptions (menu_id);",
    # The model already declared an index on razorpay_order_id; the next two
    # lines add the UNIQUE part. The DO block tolerates re-runs.
    """
    DO $$
    BEGIN
        IF NOT EXISTS (
            SELECT 1 FROM pg_constraint
            WHERE conname = 'uq_subscriptions_razorpay_order_id'
        ) THEN
            ALTER TABLE subscriptions
            ADD CONSTRAINT uq_subscriptions_razorpay_order_id
            UNIQUE (razorpay_order_id);
        END IF;
    END $$;
    """,
]


def main():
    with engine.begin() as conn:
        for stmt in STATEMENTS:
            print(f"Running: {stmt.strip()[:80]}...")
            conn.execute(text(stmt))
    print("Done.")


if __name__ == "__main__":
    main()
