import os
import sys
from dotenv import load_dotenv

# Add the project root to the python path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

load_dotenv()

from app.database import engine
from sqlalchemy import text

def migrate_meals_per_slot():
    print("Connecting to DB to make 'meals_per_slot' nullable...")
    try:
        with engine.connect() as conn:
            # Check if column exists
            result = conn.execute(text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name='plan_templates' AND column_name='meals_per_slot';"
            )).fetchone()
            
            if not result:
                print("Column 'meals_per_slot' does not exist in 'plan_templates'.")
            else:
                conn.execute(text("ALTER TABLE plan_templates ALTER COLUMN meals_per_slot DROP NOT NULL;"))
                conn.commit()
                print("Successfully set 'meals_per_slot' column as nullable in 'plan_templates'.")
    except Exception as e:
        print(f"Error during migration: {e}")

if __name__ == "__main__":
    migrate_meals_per_slot()
