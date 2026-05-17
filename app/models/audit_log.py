from sqlalchemy import Column, Integer, String, DateTime, JSON
from sqlalchemy.sql import func
from app.database import Base


class AuditLog(Base):
    """Immutable record of sensitive admin actions.

    No FK to users — deleting a target user must not cascade away the log row
    that says they were deleted. `actor_id` / `target_id` are stored as plain
    integers; resolve them back to users at read time if needed.
    """
    __tablename__ = "audit_logs"

    id          = Column(Integer, primary_key=True, autoincrement=True)
    actor_id    = Column(Integer, nullable=True, index=True)
    actor_email = Column(String, nullable=True)
    action      = Column(String, nullable=False, index=True)
    target_type = Column(String, nullable=True)
    target_id   = Column(String, nullable=True, index=True)
    details     = Column(JSON, nullable=True)
    created_at  = Column(DateTime(timezone=True), server_default=func.now(), nullable=False, index=True)
