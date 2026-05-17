"""One-shot: add is_featured boolean column to meal_tiers. Idempotent."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text
from app.database import engine

DDL = """
ALTER TABLE meal_tiers
    ADD COLUMN IF NOT EXISTS is_featured boolean NOT NULL DEFAULT false;
"""

with engine.begin() as conn:
    conn.execute(text(DDL))
    cnt = conn.execute(text("SELECT COUNT(*) FROM meal_tiers")).scalar()
    print(f"meal_tiers.is_featured ready. {cnt} tier rows.")
