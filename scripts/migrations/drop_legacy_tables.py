import os
import sys
from dotenv import load_dotenv

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
load_dotenv()

from app.database import engine
from sqlalchemy import text

def drop_legacy_tables():
    with engine.connect() as conn:
        print("Dropping legacy tables...")
        # menu_master might have a foreign key to dishes, so DROP CASCADE
        conn.execute(text("DROP TABLE IF EXISTS menu_master CASCADE;"))
        conn.execute(text("DROP TABLE IF EXISTS dishes CASCADE;"))
        conn.commit()
        print("Dropped dishes and menu_master.")

if __name__ == "__main__":
    drop_legacy_tables()
