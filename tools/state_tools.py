"""State tools — query and persist job state."""

import json
import logging
from typing import Optional

from langchain_core.tools import tool
from pydantic import BaseModel, Field

from storage import JobRepository, DecisionRepository, NotificationRepository, init_db
from storage.repositories import get_db

logger = logging.getLogger(__name__)

# Initialize DB on first import
init_db()


# ===========================================================================
# get_user_preferences
# ===========================================================================

@tool
def get_user_preferences(_: str = "") -> str:
    """
    Get the user's job search preferences: target companies, roles, keywords,
    exclusions, experience range, and confidence threshold from config.json.
    """
    from utils import load_config
    config = load_config()
    return json.dumps({
        "target_companies": config.get("target_companies", []),
        "target_roles": config.get("roles", []),
        "keywords": config.get("job_portals", [{}])[0].get("keywords", []),
        "linkedin_url": config.get("job_portals", [{}])[0].get("career_page", ""),
        "exclude_keywords": config.get("exclude_keywords", []),
        "exclude_roles": config.get("exclude_roles", []),
        "exclude_levels": config.get("exclude_levels", []),
        "experience_years": config.get("experience_years", 6),
        "min_experience_years": config.get("min_experience_years", 4),
        "confidence_threshold": config.get("confidence_threshold", 0.6),
    })


# ===========================================================================
# get_seen_jobs / save_job
# ===========================================================================

class SaveJobInput(BaseModel):
    canonical_id: str = Field(description="Canonical job ID (source:source_job_id)")
    company: str = Field(default="", description="Company name")
    title: str = Field(default="", description="Job title")
    location: str = Field(default="", description="Job location")
    source: str = Field(description="Source platform: linkedin, ats, web")
    source_job_id: str = Field(description="Platform-specific job ID")
    url: str = Field(default="", description="Job posting URL")
    description: str = Field(default="")


@tool(args_schema=SaveJobInput)
def save_job(
    canonical_id: str, source: str, source_job_id: str,
    company: str = "", title: str = "", location: str = "",
    url: str = "", description: str = "",
) -> str:
    """
    Save a discovered job to the database. Returns whether it's new or already existed.
    Uses hierarchical dedup: source+source_job_id first, then company+title+location.
    """
    # Primary dedup: source + source_job_id
    existing = JobRepository.find_by_source(source, source_job_id)
    if existing:
        JobRepository.upsert(canonical_id, company, title, location, source, source_job_id, url, description)
        return json.dumps({"status": "exists", "canonical_id": existing, "is_new": False})

    # Secondary dedup: company + title + location
    if company and title:
        secondary = JobRepository.find_by_secondary(company, title, location)
        if secondary:
            JobRepository.upsert(secondary, company, title, location, source, source_job_id, url, description)
            return json.dumps({"status": "merged", "canonical_id": secondary, "is_new": False, "merged_from": canonical_id})

    is_new = JobRepository.upsert(canonical_id, company, title, location, source, source_job_id, url, description)
    return json.dumps({"status": "created" if is_new else "updated", "canonical_id": canonical_id, "is_new": is_new})


@tool
def get_seen_jobs(status: str = "") -> str:
    """
    Query previously seen jobs. Optionally filter by status: discovered, matched, rejected, notified.
    Returns list of canonical_ids and basic info.
    """
    db = get_db()
    if status:
        rows = db.execute("SELECT canonical_id, company_normalized, title_normalized, status FROM jobs WHERE status = ? LIMIT 50", (status,)).fetchall()
    else:
        rows = db.execute("SELECT canonical_id, company_normalized, title_normalized, status FROM jobs LIMIT 50").fetchall()
    return json.dumps([dict(r) for r in rows])


# ===========================================================================
# get_job_history
# ===========================================================================

class GetJobHistoryInput(BaseModel):
    canonical_id: str = Field(description="Canonical job ID to look up")


@tool(args_schema=GetJobHistoryInput)
def get_job_history(canonical_id: str) -> str:
    """
    Get the full history for a specific job: all sources, decisions, and notifications.
    """
    db = get_db()
    job = db.execute("SELECT * FROM jobs WHERE canonical_id = ?", (canonical_id,)).fetchone()
    sources = db.execute("SELECT * FROM job_sources WHERE canonical_id = ?", (canonical_id,)).fetchall()
    decisions = db.execute("SELECT * FROM decisions WHERE canonical_id = ?", (canonical_id,)).fetchall()
    notifications = db.execute("SELECT * FROM notifications WHERE canonical_id = ?", (canonical_id,)).fetchall()

    return json.dumps({
        "job": dict(job) if job else None,
        "sources": [dict(s) for s in sources],
        "decisions": [dict(d) for d in decisions],
        "notifications": [dict(n) for n in notifications],
    })


# ===========================================================================
# record_decision / record_notification
# ===========================================================================

class RecordDecisionInput(BaseModel):
    canonical_id: str = Field(description="Job canonical ID")
    decision: str = Field(description="match, reject, or investigate")
    score: float = Field(default=0.0)
    confidence: float = Field(default=0.0)
    reasons: list[str] = Field(default_factory=list)
    investigation_depth: int = Field(default=0)


@tool(args_schema=RecordDecisionInput)
def record_decision(canonical_id: str, decision: str, score: float = 0.0,
                    confidence: float = 0.0, reasons: list[str] | None = None,
                    investigation_depth: int = 0) -> str:
    """Record an evaluation decision for a job."""
    DecisionRepository.record(
        canonical_id, decision, score, confidence,
        reasons or [], [], investigation_depth,
    )
    JobRepository.update_status(canonical_id, decision if decision != "investigate" else "investigating")
    return json.dumps({"status": "recorded", "canonical_id": canonical_id, "decision": decision})


class RecordNotificationInput(BaseModel):
    canonical_id: str = Field(description="Job canonical ID")
    success: bool = Field(default=True)


@tool(args_schema=RecordNotificationInput)
def record_notification(canonical_id: str, success: bool = True) -> str:
    """Record that a job was notified."""
    NotificationRepository.record(canonical_id, success)
    return json.dumps({"status": "recorded", "canonical_id": canonical_id, "notified": success})
