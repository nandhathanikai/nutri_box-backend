"""
supabase_errors.py
──────────────────
Utility to classify raw Supabase storage / API exceptions into structured,
human-readable error responses that can be forwarded to the frontend admin.

Usage:
    from app.utils.supabase_errors import classify_supabase_error
    raise HTTPException(status_code=code, detail=classify_supabase_error(e))
"""

import re
from typing import Tuple


# ── Known error patterns ───────────────────────────────────────────────────────

_PATTERNS = [
    # Quota / storage limit
    (
        re.compile(r"quota|storage limit|exceeded|over.*limit|capacity", re.IGNORECASE),
        "supabase_quota_exceeded",
        503,
        (
            "Supabase storage quota has been exceeded. "
            "Free up space or upgrade your Supabase plan at supabase.com/dashboard."
        ),
    ),
    # Unauthorized / invalid API key
    (
        re.compile(r"invalid api key|unauthorized|401|jwt expired|invalid token", re.IGNORECASE),
        "supabase_unauthorized",
        503,
        (
            "Supabase authorization failed. "
            "Check that SUPABASE_URL and SUPABASE_KEY are correct in the server .env file."
        ),
    ),
    # Forbidden (project paused / plan issue)
    (
        re.compile(r"forbidden|403|project.*paused|plan.*required", re.IGNORECASE),
        "supabase_forbidden",
        503,
        (
            "Access to Supabase storage was denied. "
            "Your project may be paused or your plan may have been downgraded."
        ),
    ),
    # Bucket not found
    (
        re.compile(r"bucket.*not found|no such bucket|404", re.IGNORECASE),
        "supabase_bucket_not_found",
        503,
        (
            "The configured Supabase storage bucket does not exist. "
            "Create a bucket named 'menu-images' in your Supabase Storage dashboard."
        ),
    ),
    # File too large
    (
        re.compile(r"payload too large|413|entity too large|file.*too large", re.IGNORECASE),
        "supabase_file_too_large",
        413,
        (
            "The uploaded file is too large for Supabase storage. "
            "Please compress the image and try again (max recommended: 5 MB)."
        ),
    ),
    # Network / connection
    (
        re.compile(r"connection.*refused|timeout|network|ECONNREFUSED|ETIMEDOUT", re.IGNORECASE),
        "supabase_network_error",
        503,
        (
            "Cannot reach Supabase storage service. "
            "Check your server's internet connection and Supabase project URL."
        ),
    ),
    # Duplicate / already exists
    (
        re.compile(r"already exists|duplicate|409", re.IGNORECASE),
        "supabase_duplicate",
        409,
        "A file with this name already exists in storage.",
    ),
]

_FALLBACK_TYPE = "supabase_error"
_FALLBACK_CODE = 503
_FALLBACK_MSG = (
    "An unexpected error occurred with Supabase storage. "
    "Check the server logs for more details."
)


# ── Public API ─────────────────────────────────────────────────────────────────

def classify_supabase_error(exc: Exception) -> Tuple[int, dict]:
    """
    Classify a raw Supabase exception into a (http_status_code, detail_dict) tuple.

    Returns:
        (status_code, detail) where detail is a dict with keys:
            - error_type: str  (machine-readable slug)
            - message: str     (human-readable, safe to show in admin UI)
            - raw: str         (original exception message, for debug context)
    """
    raw_msg = _extract_message(exc)

    for pattern, error_type, status_code, message in _PATTERNS:
        if pattern.search(raw_msg):
            return status_code, {
                "error_type": error_type,
                "message": message,
                "raw": raw_msg,
            }

    # Fallback — unknown error
    return _FALLBACK_CODE, {
        "error_type": _FALLBACK_TYPE,
        "message": _FALLBACK_MSG,
        "raw": raw_msg,
    }


def _extract_message(exc: Exception) -> str:
    """Pull a flat string from various exception shapes."""
    # Supabase-py StorageException has a .message attribute
    if hasattr(exc, "message") and exc.message:
        return str(exc.message)
    # httpx / requests Response wrapped in exception
    if hasattr(exc, "response") and exc.response is not None:
        try:
            body = exc.response.json()
            return str(body.get("message") or body.get("error") or body)
        except Exception:
            try:
                return exc.response.text or str(exc)
            except Exception:
                pass
    return str(exc)
