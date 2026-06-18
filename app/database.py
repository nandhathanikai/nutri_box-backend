import logging
import os

from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from sqlalchemy.orm import declarative_base, sessionmaker

load_dotenv()

logger = logging.getLogger(__name__)

DATABASE_URL = os.getenv("DATABASE_URL")

engine = create_engine(
    DATABASE_URL,
    pool_size=5,
    max_overflow=10,
    pool_pre_ping=False,
    pool_recycle=1800,
    pool_timeout=30,           # fail fast if pool is exhausted (don't hang forever)
    connect_args={
        "connect_timeout": 10, # TCP handshake timeout in seconds
    },
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def test_connection():
    """Verify database connectivity at startup and run manual schema migrations."""
    try:
        with engine.connect() as conn:
            result = conn.execute(text("SELECT version()"))
            logger.info("DB Connected! PostgreSQL version: %s", result.fetchone()[0])
            
            # Manual schema migration for subscriptions table
            conn.execute(text("ALTER TABLE subscriptions ADD COLUMN IF NOT EXISTS customization_details VARCHAR;"))
            conn.execute(text("ALTER TABLE subscriptions ADD COLUMN IF NOT EXISTS diet_type VARCHAR;"))
            conn.execute(text("ALTER TABLE subscriptions ADD COLUMN IF NOT EXISTS slot_combo VARCHAR;"))
            # Manual schema migration for custom_plan_requests table
            conn.execute(text("ALTER TABLE custom_plan_requests ADD COLUMN IF NOT EXISTS admin_note TEXT;"))
            conn.commit()
            logger.info("Database schema upgrades checked & applied successfully.")
    except Exception as e:
        logger.error("DB Connection or schema migration failed: %s", e)