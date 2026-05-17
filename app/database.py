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
    pool_size=5,           # Persistent connections kept open
    max_overflow=10,       # Extra connections allowed under burst load
    pool_pre_ping=True,    # Verify connection is alive before handing it out
    pool_recycle=1800,     # Recycle connections after 30 min (avoids stale TCP)
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
    """Verify database connectivity at startup."""
    try:
        with engine.connect() as conn:
            result = conn.execute(text("SELECT version()"))
            logger.info("DB Connected! PostgreSQL version: %s", result.fetchone()[0])
    except Exception as e:
        logger.error("DB Connection failed: %s", e)