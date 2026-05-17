"""Lightweight in-process scheduler for credit + offer maintenance jobs.

Single-instance deploys only. For multi-instance, replace this with a
distributed cron (e.g. external systemd timer, GH Actions cron, or a real
job queue) so the same job doesn't run twice.
"""
from __future__ import annotations
import logging
import threading
import time
from datetime import datetime, time as dtime, timedelta
from typing import Callable

from app.database import SessionLocal
from app.jobs.credit_jobs import (
    promote_pending_credits,
    mark_delivered,
    expire_stale_credits,
    delete_inactive_accounts,
)

logger = logging.getLogger(__name__)

# Run daily at 02:00 server-local
DAILY_RUN_HOUR = 2
DAILY_RUN_MINUTE = 0


def _seconds_until_next_run() -> float:
    now = datetime.now()
    target = datetime.combine(now.date(), dtime(DAILY_RUN_HOUR, DAILY_RUN_MINUTE))
    if target <= now:
        target += timedelta(days=1)
    return (target - now).total_seconds()


def _run_safely(label: str, fn: Callable):
    try:
        with SessionLocal() as db:
            count = fn(db)
            logger.info("[scheduler] %s: %s", label, count)
    except Exception as exc:
        logger.error("[scheduler] %s FAILED: %s", label, exc, exc_info=True)


def _daily_loop():
    while True:
        wait = _seconds_until_next_run()
        time.sleep(wait)
        _run_safely("promote_pending_credits", promote_pending_credits)
        _run_safely("mark_delivered", mark_delivered)
        _run_safely("expire_stale_credits", expire_stale_credits)
        _run_safely("delete_inactive_accounts", delete_inactive_accounts)


_thread: threading.Thread | None = None


def start_scheduler():
    """Boot the scheduler thread once. Idempotent — safe to call multiple times."""
    global _thread
    if _thread and _thread.is_alive():
        return
    _thread = threading.Thread(target=_daily_loop, name="nutribox-scheduler", daemon=True)
    _thread.start()
    logger.info(
        "[scheduler] started — next run at %02d:%02d server-local",
        DAILY_RUN_HOUR, DAILY_RUN_MINUTE,
    )

