import os
from dotenv import load_dotenv
from sqlalchemy import create_engine, text, inspect

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")
if DATABASE_URL and DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

engine = create_engine(DATABASE_URL)

def check_columns():
    inspector = inspect(engine)
    columns = inspector.get_columns('meal_tiers')
    print("COLUMNS IN meal_tiers:")
    for col in columns:
        print(f"- {col['name']}: {col['type']}")

if __name__ == "__main__":
    check_columns()
