"""
Shared utility functions for the Company Tracking application.

Handles JSON file I/O, cleanup scheduling, seen-jobs tracking,
and Telegram notifications.
"""

import json
import logging
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

import requests
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Paths (relative to this file so the app works from any CWD)
# ---------------------------------------------------------------------------
_HERE = Path(__file__).resolve().parent
SEEN_JOBS_FILE = _HERE / "seen_jobs.json"
CLEANUP_META_FILE = _HERE / "cleanup_meta.json"
CONFIG_FILE = _HERE / "config.json"

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
CLEANUP_DAYS = 10
MIN_JOB_ID_LENGTH = 5  # real LinkedIn job IDs are 10 digits; 5 is a safety floor


# ===================================================================
# Generic JSON helpers
# ===================================================================

def load_json(path: Path, default: Any = None) -> Any:
    """Load and parse a JSON file, returning *default* on any error."""
    try:
        with open(path) as fh:
            return json.load(fh)
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def save_json(path: Path, data: Any) -> None:
    """Atomically write *data* as JSON (tmp + rename)."""
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w") as fh:
        json.dump(data, fh)
    tmp.replace(path)


# ===================================================================
# Configuration
# ===================================================================

def load_config() -> dict:
    """Load the job-search configuration from config.json."""
    cfg = load_json(CONFIG_FILE, default={})
    if not cfg:
        raise RuntimeError(f"config.json is missing or empty at {CONFIG_FILE}")
    return cfg


# ===================================================================
# Seen-jobs tracking
# ===================================================================

def load_seen_jobs() -> set[str]:
    """Return the set of already-seen job IDs."""
    raw = load_json(SEEN_JOBS_FILE, default=[])
    # Filter out any entries that are too short to be real job IDs
    return {str(jid) for jid in raw if isinstance(jid, (str, int)) and len(str(jid)) >= MIN_JOB_ID_LENGTH}


def save_seen_jobs(jobs: set[str]) -> None:
    """Persist the seen-jobs set."""
    save_json(SEEN_JOBS_FILE, sorted(jobs))


def is_job_seen(job_id: str) -> bool:
    """Check whether a single job ID has already been processed."""
    seen = load_seen_jobs()
    return job_id in seen


def mark_job_seen(job_id: str) -> None:
    """Add a job ID to the seen set and persist immediately."""
    if len(str(job_id)) < MIN_JOB_ID_LENGTH:
        return  # silently ignore bogus IDs
    seen = load_seen_jobs()
    seen.add(str(job_id))
    save_seen_jobs(seen)


# ===================================================================
# Periodic cleanup
# ===================================================================

def check_and_cleanup() -> bool:
    """Clear seen_jobs.json every CLEANUP_DAYS.  Returns True if cleaned."""
    now = datetime.now(timezone.utc)
    meta = load_json(CLEANUP_META_FILE, default={})
    last_str: Optional[str] = meta.get("last_cleanup")

    if not last_str:
        save_json(CLEANUP_META_FILE, {"last_cleanup": now.isoformat()})
        return False

    try:
        last_dt = datetime.fromisoformat(last_str)
    except ValueError:
        save_json(CLEANUP_META_FILE, {"last_cleanup": now.isoformat()})
        return False

    if last_dt.tzinfo is None:
        last_dt = last_dt.replace(tzinfo=timezone.utc)

    if now - last_dt >= timedelta(days=CLEANUP_DAYS):
        save_json(SEEN_JOBS_FILE, [])
        save_json(CLEANUP_META_FILE, {"last_cleanup": now.isoformat()})
        return True

    return False


# ===================================================================
# Telegram
# ===================================================================

def send_telegram(message: str) -> bool:
    """Send a Telegram message.  Returns True on success."""
    token = os.getenv("TELEGRAM_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")

    if not token or not chat_id:
        logger.warning("Telegram not configured — skipping notification")
        return False

    try:
        resp = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": message},
            timeout=10,
        )
        if resp.status_code == 200:
            body = resp.json()
            if body.get("ok"):
                return True
            logger.error("Telegram API error: %s (code %s)", body.get("description", "unknown"), body.get("error_code", "?"))
        else:
            logger.error("Telegram HTTP %d: %s", resp.status_code, resp.text[:200])
        return False
    except requests.RequestException as e:
        logger.error("Telegram request failed: %s", e)
        return False
