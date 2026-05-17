"""
Migration: Credits V2 - Session-level bonus meal delivery

Adds new columns: session, original_delivery_date, delivery_on, is_manual
Backfills from linked DeliveryCancellation records.
Converts old statuses: available -> scheduled, applied -> delivered
Drops old columns: available_from, applied_to_plan_id, applied_at

Run: python migrate_credits_v2.py
"""
import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

from app.database import engine
from sqlalchemy import text

def run_migration():
    with engine.connect() as conn:
        # -- Step 1: Add new columns
        new_columns = [
            ("session",                "VARCHAR(50)"),
            ("original_delivery_date", "DATE"),
            ("delivery_on",            "DATE"),
            ("is_manual",              "BOOLEAN DEFAULT FALSE"),
        ]

        for col_name, col_type in new_columns:
            try:
                conn.execute(text(f"ALTER TABLE credits ADD COLUMN {col_name} {col_type}"))
                print(f"  [OK] Added column: credits.{col_name}")
            except Exception as e:
                if "already exists" in str(e).lower() or "duplicate" in str(e).lower():
                    print(f"  [SKIP] Column credits.{col_name} already exists, skipping")
                else:
                    print(f"  [WARN] Error adding credits.{col_name}: {e}")
            conn.commit()

        # -- Step 2: Backfill session and original_delivery_date from cancellations
        print("\n  Backfilling session and original_delivery_date from delivery_cancellations...")
        try:
            conn.execute(text("""
                UPDATE credits
                SET session = dc.session,
                    original_delivery_date = dc.delivery_date
                FROM delivery_cancellations dc
                WHERE credits.cancellation_id = dc.id
                  AND (credits.session IS NULL OR credits.original_delivery_date IS NULL)
            """))
            conn.commit()
            print("  [OK] Backfill complete")
        except Exception as e:
            print(f"  [WARN] Backfill error: {e}")
            conn.rollback()

        # Fill any remaining nulls (manual credits or orphaned records)
        try:
            conn.execute(text("""
                UPDATE credits
                SET session = 'UNKNOWN'
                WHERE session IS NULL
            """))
            conn.execute(text("""
                UPDATE credits
                SET original_delivery_date = COALESCE(plan_end_date, CURRENT_DATE)
                WHERE original_delivery_date IS NULL
            """))
            conn.commit()
            print("  [OK] Null cleanup complete")
        except Exception as e:
            print(f"  [WARN] Null cleanup error: {e}")
            conn.rollback()

        # -- Step 3: Convert old statuses
        status_map = {
            "available": "scheduled",
            "applied":   "delivered",
            "expired":   "not_eligible",
        }
        for old_status, new_status in status_map.items():
            try:
                result = conn.execute(text(
                    f"UPDATE credits SET status = '{new_status}' WHERE status = '{old_status}'"
                ))
                count = result.rowcount
                conn.commit()
                if count > 0:
                    print(f"  [OK] Converted {count} credits: {old_status} -> {new_status}")
                else:
                    print(f"  [SKIP] No credits with status '{old_status}'")
            except Exception as e:
                print(f"  [WARN] Status conversion error ({old_status}): {e}")
                conn.rollback()

        # -- Step 4: Set delivery_on for scheduled credits
        try:
            conn.execute(text("""
                UPDATE credits
                SET delivery_on = COALESCE(delivery_on, plan_end_date + INTERVAL '1 day')
                WHERE status = 'scheduled' AND delivery_on IS NULL
            """))
            conn.commit()
            print("  [OK] Set delivery_on for scheduled credits")
        except Exception as e:
            print(f"  [WARN] delivery_on backfill error: {e}")
            conn.rollback()

        # -- Step 5: Make session NOT NULL
        try:
            conn.execute(text("ALTER TABLE credits ALTER COLUMN session SET NOT NULL"))
            conn.commit()
            print("  [OK] Set credits.session as NOT NULL")
        except Exception as e:
            print(f"  [WARN] NOT NULL constraint error: {e}")
            conn.rollback()

        try:
            conn.execute(text("ALTER TABLE credits ALTER COLUMN original_delivery_date SET NOT NULL"))
            conn.commit()
            print("  [OK] Set credits.original_delivery_date as NOT NULL")
        except Exception as e:
            print(f"  [WARN] NOT NULL constraint error: {e}")
            conn.rollback()

        # -- Step 6: Drop old columns (optional - safe to keep)
        old_columns = ["available_from", "applied_to_plan_id", "applied_at"]
        for col in old_columns:
            try:
                conn.execute(text(f"ALTER TABLE credits DROP COLUMN IF EXISTS {col}"))
                conn.commit()
                print(f"  [OK] Dropped old column: credits.{col}")
            except Exception as e:
                print(f"  [WARN] Could not drop credits.{col}: {e}")
                conn.rollback()

        # Make cancellation_id and subscription_id nullable
        try:
            conn.execute(text("ALTER TABLE credits ALTER COLUMN cancellation_id DROP NOT NULL"))
            conn.commit()
            print("  [OK] Made credits.cancellation_id nullable")
        except Exception as e:
            print(f"  [WARN] Nullable error: {e}")
            conn.rollback()

        try:
            conn.execute(text("ALTER TABLE credits ALTER COLUMN subscription_id DROP NOT NULL"))
            conn.commit()
            print("  [OK] Made credits.subscription_id nullable")
        except Exception as e:
            print(f"  [WARN] Nullable error: {e}")
            conn.rollback()

        print("\n[DONE] Migration complete!")


if __name__ == "__main__":
    print("=" * 60)
    print("  Credits V2 Migration - Session-Level Bonus Meals")
    print("=" * 60)
    run_migration()
