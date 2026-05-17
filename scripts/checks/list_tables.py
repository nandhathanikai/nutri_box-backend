import os
import sys
from dotenv import load_dotenv

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
load_dotenv()

from app.database import engine
from sqlalchemy import text

def list_tables():
    with engine.connect() as conn:
        result = conn.execute(text("SELECT table_name FROM information_schema.tables WHERE table_schema='public';"))
        tables = [row[0] for row in result.fetchall()]
        print("TABLES IN DB:")
        for t in tables:
            print("-", t)

if __name__ == "__main__":
    list_tables()
