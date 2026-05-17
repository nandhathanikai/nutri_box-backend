from app.database import engine
from sqlalchemy import text

def check_structure():
    with engine.connect() as conn:
        for table in ['meal_tiers', 'plan_templates', 'subscriptions', 'weekly_menus']:
            print(f"\n--- {table} ---")
            res = conn.execute(text(f"SELECT column_name, data_type FROM information_schema.columns WHERE table_name='{table}';")).fetchall()
            for row in res:
                print(f"{row[0]}: {row[1]}")

if __name__ == "__main__":
    check_structure()
