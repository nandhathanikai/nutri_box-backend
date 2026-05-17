import os
import sys
from dotenv import load_dotenv

# Add the project root to the python path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

load_dotenv()

from app.database import engine
from sqlalchemy import text

def add_name_column():
    print("Connecting to DB to add the 'name' column...")
    try:
        with engine.connect() as conn:
            # Check if column exists
            result = conn.execute(text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name='plan_templates' AND column_name='name';"
            )).fetchone()
            
            if result:
                print("Column 'name' already exists in 'plan_templates'.")
            else:
                conn.execute(text("ALTER TABLE plan_templates ADD COLUMN name TEXT DEFAULT '';"))
                conn.commit()
                print("Successfully added 'name' column to 'plan_templates'.")
    except Exception as e:
        print(f"Error during migration: {e}")

if __name__ == "__main__":
    add_name_column()
