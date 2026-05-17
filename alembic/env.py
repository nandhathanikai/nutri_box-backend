"""Alembic environment configuration for Nutribox.

Loads DATABASE_URL from .env and makes all SQLAlchemy models visible to
autogenerate by importing Base and every model module.
"""
import os
import sys
from logging.config import fileConfig

from alembic import context
from dotenv import load_dotenv
from sqlalchemy import create_engine, pool

# Ensure the backend package is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

load_dotenv()

# Alembic Config object — provides access to alembic.ini values
config = context.config

# Set up Python logging from the alembic.ini [loggers] section
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Read the DB URL directly — we do NOT use config.set_main_option because
# ConfigParser chokes on percent-encoded chars (e.g. %40 in passwords).
DATABASE_URL = os.getenv("DATABASE_URL", "")

# ── Import Base and ALL model modules so autogenerate can see them ────────────
from app.database import Base  # noqa: E402

from app.models import user          # noqa: F401, E402
from app.models import subscription  # noqa: F401, E402
from app.models import menu          # noqa: F401, E402
from app.models import credit        # noqa: F401, E402
from app.models import settings      # noqa: F401, E402
from app.models import marketing     # noqa: F401, E402
from app.models import audit_log     # noqa: F401, E402
from app.models import meal_tier     # noqa: F401, E402

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode — generates SQL without a live DB."""
    context.configure(
        url=DATABASE_URL,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode — connects to the DB and applies."""
    connectable = create_engine(DATABASE_URL, poolclass=pool.NullPool)
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()

