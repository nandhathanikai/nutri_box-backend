from app.database import engine
from sqlalchemy import text

with engine.connect() as conn:
    res = conn.execute(text("SELECT id, name, slug FROM meal_tiers;")).fetchall()
    for row in res:
        print(row)
