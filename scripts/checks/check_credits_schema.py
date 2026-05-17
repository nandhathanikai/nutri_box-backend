from app.database import engine
from sqlalchemy import text

with engine.connect() as conn:
    result = conn.execute(text("SELECT column_name FROM information_schema.columns WHERE table_name = 'credits' ORDER BY ordinal_position"))
    cols = [r[0] for r in result]
    print("Credits table columns:", cols)
    
    # Also check if table exists
    if not cols:
        print("Credits table does not exist or has no columns!")
    else:
        print(f"Total columns: {len(cols)}")
