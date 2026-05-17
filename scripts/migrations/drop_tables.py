from app.database import engine
from sqlalchemy import text
from app.routers.menu import Base

with engine.connect() as conn:
    conn.execute(text("DROP TABLE IF EXISTS weekly_menus CASCADE;"))
    conn.execute(text("DROP TABLE IF EXISTS dishes CASCADE;"))
    conn.commit()

Base.metadata.create_all(bind=engine)
print('Tables dropped successfully!')
