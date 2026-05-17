import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# ── Logging — must be configured before any other app imports ────────────────
from app.logging_config import setup_logging
setup_logging()

logger = logging.getLogger(__name__)

from app.database import engine, test_connection, Base
from app.models.user import User  # noqa: F401  registers users table
from app.models.subscription import Subscription  # noqa: F401
from app.models import menu as menu_models  # noqa: F401  registers TierPricing, WeeklyMenuImage, PlanTemplate
from app.models import credit as credit_models  # noqa: F401  registers DeliveryCancellation, Credit
from app.models import settings as settings_models  # noqa: F401  registers AppSettings
from app.models import marketing as marketing_models  # noqa: F401  registers Announcement, Offer
from app.models import audit_log as audit_log_models  # noqa: F401  registers AuditLog
from app.routers import auth, admin, menu, settings
from app.routers import announcements as announcements_router
from app.routers import offers as offers_router
from app.routers import subscriptions as subscriptions_router
from app.routers import credits as credits_router
from app.routers import payments as payments_router
from app.jobs.scheduler import start_scheduler


# ── Lifespan (replaces deprecated @app.on_event) ────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup / shutdown lifecycle for the application."""
    # ── Startup ──
    test_connection()

    if os.getenv("AUTO_CREATE_TABLES", "").lower() in ("1", "true", "yes"):
        Base.metadata.create_all(bind=engine)
        logger.info("Database tables created/verified (AUTO_CREATE_TABLES=true)")
    else:
        logger.info("Skipping create_all — use 'alembic upgrade head' for migrations")

    if os.getenv("DISABLE_SCHEDULER", "").lower() not in ("1", "true", "yes"):
        start_scheduler()

    yield  # ← application runs here

    # ── Shutdown ──
    logger.info("Nutribox API shutting down")


app = FastAPI(title="Nutribox API", version="1.0.0", lifespan=lifespan)

# CORS — additional origins can be set via FRONTEND_ORIGINS env (comma-separated).
_default_origins = [
    "http://localhost:4200",
    "http://localhost:57298",
    "http://127.0.0.1:4200",
    "http://127.0.0.1:57298",
]
_extra_origins = [o.strip() for o in os.getenv("FRONTEND_ORIGINS", "").split(",") if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_default_origins + _extra_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "Accept", "X-Requested-With"],
)

# Routers
app.include_router(auth.router, prefix="/api/auth")
app.include_router(admin.router, prefix="/api/admin")
app.include_router(menu.router)
app.include_router(credits_router.router)
app.include_router(settings.router, prefix="/api")
app.include_router(announcements_router.router)
app.include_router(offers_router.router)
app.include_router(subscriptions_router.router)
app.include_router(payments_router.router)


@app.get("/")
def root():
    return {"message": "Nutribox API is running"}


@app.get("/healthz")
def health():
    """Liveness probe — does NOT touch the database (so a DB outage doesn't take the pod down)."""
    return {"status": "ok"}

