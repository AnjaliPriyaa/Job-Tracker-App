"""Repository classes for database operations."""

import json
from datetime import datetime, timezone
from typing import Optional

from storage.database import get_db


class JobRepository:
    """CRUD operations for jobs."""

    @staticmethod
    def upsert(canonical_id: str, company: str, title: str, location: str,
               source: str, source_job_id: str, url: str, description: str = "") -> bool:
        """Insert or update a job. Returns True if newly created."""
        db = get_db()
        now = datetime.now(timezone.utc).isoformat()
        company_norm = " ".join(company.lower().strip().split())
        title_norm = " ".join(title.lower().strip().split())
        location_norm = " ".join(location.lower().strip().split())

        existing = db.execute(
            "SELECT canonical_id FROM jobs WHERE canonical_id = ?", (canonical_id,)
        ).fetchone()

        if existing:
            db.execute(
                "UPDATE jobs SET last_seen = ?, company_normalized = ?, title_normalized = ?, location_normalized = ? WHERE canonical_id = ?",
                (now, company_norm, title_norm, location_norm, canonical_id),
            )
            is_new = False
        else:
            db.execute(
                "INSERT INTO jobs (canonical_id, company_normalized, title_normalized, location_normalized, first_seen, last_seen) VALUES (?, ?, ?, ?, ?, ?)",
                (canonical_id, company_norm, title_norm, location_norm, now, now),
            )
            is_new = True

        # Upsert source
        db.execute(
            """INSERT OR IGNORE INTO job_sources (canonical_id, source, source_job_id, url, title, company, location, description)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (canonical_id, source, source_job_id, url, title, company, location, description),
        )
        db.commit()
        return is_new

    @staticmethod
    def find_by_secondary(company: str, title: str, location: str) -> Optional[str]:
        """Find canonical_id by normalized company+title+location. Returns None if not found."""
        db = get_db()
        cn = " ".join(company.lower().strip().split())
        tn = " ".join(title.lower().strip().split())
        ln = " ".join(location.lower().strip().split())
        row = db.execute(
            "SELECT canonical_id FROM jobs WHERE company_normalized = ? AND title_normalized = ? AND location_normalized = ?",
            (cn, tn, ln),
        ).fetchone()
        return row["canonical_id"] if row else None

    @staticmethod
    def find_by_source(source: str, source_job_id: str) -> Optional[str]:
        """Find canonical_id by source+source_job_id."""
        db = get_db()
        row = db.execute(
            "SELECT canonical_id FROM job_sources WHERE source = ? AND source_job_id = ?",
            (source, source_job_id),
        ).fetchone()
        return row["canonical_id"] if row else None

    @staticmethod
    def is_notified(canonical_id: str, recency_days: int = 30) -> bool:
        """Check if a job has been notified within the recency window.
        Jobs notified more than recency_days ago can be reconsidered
        (e.g., for updated/reposted listings)."""
        db = get_db()
        cutoff = (datetime.now(timezone.utc).replace(hour=0, minute=0, second=0) -
                  __import__('datetime').timedelta(days=recency_days)).isoformat()
        row = db.execute(
            "SELECT COUNT(*) as cnt FROM notifications WHERE canonical_id = ? AND success = 1 AND sent_at >= ?",
            (canonical_id, cutoff),
        ).fetchone()
        return row["cnt"] > 0

    @staticmethod
    def should_reconsider(canonical_id: str, recency_days: int = 30) -> bool:
        """Check if a seen job should be reconsidered (notified long ago)."""
        db = get_db()
        cutoff = (datetime.now(timezone.utc).replace(hour=0, minute=0, second=0) -
                  __import__('datetime').timedelta(days=recency_days)).isoformat()
        row = db.execute(
            "SELECT last_seen FROM jobs WHERE canonical_id = ?", (canonical_id,)
        ).fetchone()
        if not row:
            return True
        return row["last_seen"] < cutoff

    @staticmethod
    def update_status(canonical_id: str, status: str) -> None:
        db = get_db()
        db.execute("UPDATE jobs SET status = ?, last_seen = ? WHERE canonical_id = ?",
                   (status, datetime.now(timezone.utc).isoformat(), canonical_id))
        db.commit()


class DecisionRepository:
    """Record evaluation decisions."""

    @staticmethod
    def record(canonical_id: str, decision: str, score: float, confidence: float,
               reasons: list[str], missing_info: list[str], investigation_depth: int = 0) -> None:
        db = get_db()
        db.execute(
            "INSERT INTO decisions (canonical_id, decision, score, confidence, reasons, missing_info, investigation_depth, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (canonical_id, decision, score, confidence, json.dumps(reasons), json.dumps(missing_info),
             investigation_depth, datetime.now(timezone.utc).isoformat()),
        )
        db.commit()

    @staticmethod
    def get_investigation_depth(canonical_id: str) -> int:
        db = get_db()
        row = db.execute(
            "SELECT MAX(investigation_depth) as d FROM decisions WHERE canonical_id = ?",
            (canonical_id,),
        ).fetchone()
        return row["d"] or 0


class NotificationRepository:
    """Record sent notifications."""

    @staticmethod
    def record(canonical_id: str, success: bool, message_id: str = "") -> None:
        db = get_db()
        db.execute(
            "INSERT INTO notifications (canonical_id, sent_at, success, telegram_message_id) VALUES (?, ?, ?, ?)",
            (canonical_id, datetime.now(timezone.utc).isoformat(), 1 if success else 0, message_id),
        )
        if success:
            db.execute("UPDATE jobs SET notified = 1, status = 'notified' WHERE canonical_id = ?", (canonical_id,))
        db.commit()

    @staticmethod
    def count_today() -> int:
        """Count notifications sent today for rate limiting."""
        db = get_db()
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        row = db.execute(
            "SELECT COUNT(*) as cnt FROM notifications WHERE success = 1 AND sent_at >= ?",
            (today,),
        ).fetchone()
        return row["cnt"]
