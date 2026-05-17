"""Gunicorn configuration for production deployment.

Run with:
    gunicorn app.main:app -c gunicorn.conf.py
"""

import multiprocessing
import os

# ── Server socket ────────────────────────────────────────────────────────────
bind = os.getenv("BIND", "0.0.0.0:8000")

# ── Worker processes ─────────────────────────────────────────────────────────
# Recommended formula: min(cpu_count * 2 + 1, 4) — cap at 4 for most
# single-dyno / small-VPS deployments to avoid exhausting DB connections.
workers = min(multiprocessing.cpu_count() * 2 + 1, int(os.getenv("WEB_CONCURRENCY", "4")))
worker_class = "uvicorn.workers.UvicornWorker"

# ── Timeouts ─────────────────────────────────────────────────────────────────
timeout = 120          # Kill workers that hang longer than this
graceful_timeout = 30  # Seconds to finish in-flight requests on SIGTERM
keepalive = 5          # Keep-alive for idle connections

# ── Logging ──────────────────────────────────────────────────────────────────
# Let app-level logging handle formatting (see app/logging_config.py).
accesslog = "-"        # stdout
errorlog = "-"         # stdout
loglevel = os.getenv("LOG_LEVEL", "info").lower()

# ── Process naming ───────────────────────────────────────────────────────────
proc_name = "nutribox-api"

# ── Preloading ───────────────────────────────────────────────────────────────
# Preload the app so models / DB connections are shared across forks.
# Trade-off: code changes require a full restart (no hot-reload).
preload_app = True
