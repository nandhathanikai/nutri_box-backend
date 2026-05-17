import os
import sys
from dotenv import load_dotenv

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
load_dotenv()

from app.database import engine
from sqlalchemy import text

def migrate_weekly_menus():
    with engine.connect() as conn:
        print("Migrating weekly_menus table...")
        # Check if dish_id columns exist before dropping (just in case)
        result = conn.execute(text(
            "SELECT column_name FROM information_schema.columns WHERE table_name='weekly_menus';"
        ))
        columns = [row[0] for row in result.fetchall()]
        
        if "dish_id" in columns:
            conn.execute(text("ALTER TABLE weekly_menus DROP COLUMN dish_id CASCADE;"))
            conn.execute(text("ALTER TABLE weekly_menus DROP COLUMN day_of_week CASCADE;"))
            conn.execute(text("ALTER TABLE weekly_menus DROP COLUMN meal_slot CASCADE;"))
            
        if "image_url" not in columns:
            conn.execute(text("ALTER TABLE weekly_menus ADD COLUMN image_url TEXT DEFAULT '';"))
            
        conn.commit()
        print("Migrated weekly_menus successfully.")

if __name__ == "__main__":
    migrate_weekly_menus()
