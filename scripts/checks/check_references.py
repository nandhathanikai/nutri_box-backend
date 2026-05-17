from app.database import engine
from sqlalchemy import text

with engine.connect() as conn:
    print("--- References in plan_templates ---")
    res = conn.execute(text("SELECT tier_id, count(*) FROM plan_templates GROUP BY tier_id;")).fetchall()
    for row in res:
        tier_name = conn.execute(text("SELECT name FROM meal_tiers WHERE id = :id"), {"id": row[0]}).scalar()
        print(f"Tier ID: {row[0]}, Name: {tier_name}, Count: {row[1]}")

    print("\n--- References in weekly_menus ---")
    res = conn.execute(text("SELECT tier_id, count(*) FROM weekly_menus GROUP BY tier_id;")).fetchall()
    for row in res:
        tier_name = conn.execute(text("SELECT name FROM meal_tiers WHERE id = :id"), {"id": row[0]}).scalar()
        print(f"Tier ID: {row[0]}, Name: {tier_name}, Count: {row[1]}")
