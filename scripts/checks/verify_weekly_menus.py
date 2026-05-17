import os
import sys
from dotenv import load_dotenv

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
load_dotenv()

from app.database import engine
from sqlalchemy import text

def verify_table():
    with engine.connect() as conn:
        result = conn.execute(text(
            "SELECT column_name FROM information_schema.columns WHERE table_name='weekly_menus';"
        ))
        columns = [row[0] for row in result.fetchall()]
        print("Weekly Menus Columns:", columns)
        
        if "week_start_date" in columns and "menu_date" not in columns:
            print("Renaming week_start_date to menu_date...")
            # We also need to drop the unique constraint before renaming if it references it
            conn.execute(text("ALTER TABLE weekly_menus DROP CONSTRAINT IF EXISTS uq_weekly_menus_tier_week;"))
            conn.execute(text("ALTER TABLE weekly_menus RENAME COLUMN week_start_date TO menu_date;"))
            conn.commit()
            print("Successfully migrated weekly_menus.")

if __name__ == "__main__":
    verify_table()
