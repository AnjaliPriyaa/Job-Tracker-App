"""
Shared utility functions for the Company Tracking application.

Handles JSON file I/O, cleanup scheduling, seen-jobs tracking,
and Telegram notifications.
"""

import json
import logging
import os
import re
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
SEEN_JOBS_LINKEDIN_FILE = _HERE / "seen_jobs_linkedin.json"
SEEN_JOBS_CAREER_PAGES_FILE = _HERE / "seen_jobs_career_pages.json"
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
    """Write *data* as JSON directly."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as fh:
        json.dump(data, fh)


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


def is_job_seen(job_id: str, source: str = "") -> bool:
    """Check whether a single job ID has already been processed."""
    if source == "linkedin":
        return job_id in load_seen_jobs_linkedin()
    elif source == "career_page":
        return job_id in load_seen_jobs_career_pages()
    seen = load_seen_jobs()
    return job_id in seen


def mark_job_seen(job_id: str, source: str = "") -> None:
    """Add a job ID to the seen set and persist immediately."""
    if len(str(job_id)) < MIN_JOB_ID_LENGTH:
        return
    if source == "linkedin":
        seen = load_seen_jobs_linkedin()
        seen.add(str(job_id))
        save_seen_jobs_linkedin(seen)
    elif source == "career_page":
        seen = load_seen_jobs_career_pages()
        seen.add(str(job_id))
        save_seen_jobs_career_pages(seen)
    else:
        seen = load_seen_jobs()
        seen.add(str(job_id))
        save_seen_jobs(seen)


def load_seen_jobs_linkedin() -> set[str]:
    """Return the set of already-seen LinkedIn job IDs."""
    raw = load_json(SEEN_JOBS_LINKEDIN_FILE, default=[])
    return {str(jid) for jid in raw if isinstance(jid, (str, int))}


def save_seen_jobs_linkedin(jobs: set[str]) -> None:
    """Persist the LinkedIn seen-jobs set."""
    save_json(SEEN_JOBS_LINKEDIN_FILE, sorted(jobs))


def load_seen_jobs_career_pages() -> set[str]:
    """Return the set of already-seen career page job IDs."""
    raw = load_json(SEEN_JOBS_CAREER_PAGES_FILE, default=[])
    return {str(jid) for jid in raw if isinstance(jid, (str, int))}


def save_seen_jobs_career_pages(jobs: set[str]) -> None:
    """Persist the career pages seen-jobs set."""
    save_json(SEEN_JOBS_CAREER_PAGES_FILE, sorted(jobs))


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

# ===================================================================
# Location filter
# ===================================================================

# Non-India location patterns to reject
_REJECT_LOCATIONS = [
    r'\b(?:London|Manchester|Birmingham|Edinburgh|Glasgow|Bristol|Leeds)\b',
    r'\b(?:New York|San Francisco|Seattle|Austin|Chicago|Boston|Los Angeles|Denver|Portland|Miami|Atlanta|Dallas)\b',
    r'\b(?:Poland|Warsaw|Krak[oó]w|Gda[nń]sk|Wroc[łl]aw)\b',
    r'\b(?:Toronto|Vancouver|Montreal|Ottawa|Calgary)\b',
    r'\b(?:Berlin|Munich|Hamburg|Frankfurt|Stuttgart)\b',
    r'\b(?:Paris|Lyon|Marseille|Toulouse)\b',
    r'\b(?:Sydney|Melbourne|Brisbane|Perth)\b',
    r'\b(?:Tokyo|Osaka|Kyoto)\b',
    r'\b(?:Dubai|Abu Dhabi|Riyadh)\b',
    r'\b(?:Singapore|Hong Kong|Taipei|Seoul)\b',
    r'\b(?:Dublin|Cork)\b',
    r'\b(?:Amsterdam|Rotterdam|Eindhoven)\b',
    r'\b(?:Stockholm|Oslo|Copenhagen|Helsinki)\b',
    r'\b(?:Z[uü]rich|Geneva|Basel)\b',
    r'\b(?:UK\b|United Kingdom)\b',
    r'\b\bUS\b(?:\s*$|[,.)])\b',
]

# Acceptable location patterns
_ACCEPT_LOCATIONS = [
    r'\b(?:Bengaluru|Bangalore)\b',
    r'\b(?:Hyderabad|Secunderabad)\b',
    r'\bIndia\b',
    r'\bRemote\b',
]

def is_valid_location(description: str) -> bool:
    """
    Check if a job's location is acceptable.
    Accepts: Bengaluru/Bangalore, Hyderabad, India, or Remote (without specific non-India location).
    Rejects: Jobs explicitly in other countries/cities.
    """
    text = description.lower()
    text_head = text[:500]  # Location usually mentioned early

    # Check for non-India locations (strong reject signal)
    for pattern in _REJECT_LOCATIONS:
        if re.search(pattern, text_head):
            return False

    # Check for acceptable locations
    for pattern in _ACCEPT_LOCATIONS:
        if re.search(pattern, text_head):
            return True

    # If no location mentioned at all, let it through (conservative)
    return True


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
