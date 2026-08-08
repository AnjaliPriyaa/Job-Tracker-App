"""
Deterministic policy engine for notification validation.

All notification requests go through PolicyEngine.validate_notification().
The AI agent CANNOT bypass this — there is no other code path to Telegram.
"""

import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

from storage import JobRepository, NotificationRepository
from storage.database import get_db


def _load_config():
    _config_path = Path(__file__).resolve().parent.parent / "config.json"
    with open(_config_path) as _f:
        return json.load(_f)

logger = logging.getLogger(__name__)

# Non-India location patterns (moved from old utils.is_valid_location)
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
    r'\bUS\b',
]

_ACCEPT_LOCATIONS = [
    r'\b(?:Bengaluru|Bangalore)\b',
    r'\b(?:Hyderabad|Secunderabad)\b',
    r'\bIndia\b',
    r'\bRemote\b',
]


@dataclass
class PolicyResult:
    allowed: bool
    reason: str = ""


@dataclass
class PolicyEngine:
    """Deterministic policy validation. No AI involvement."""

    max_notifications_per_day: int = 20
    min_confidence: float = 0.6

    _config: dict = field(default_factory=_load_config)

    def validate_notification(self, canonical_id: str, company: str, title: str,
                               location: str = "", description: str = "") -> PolicyResult:
        """Run all policy checks. Returns allowed + reason."""
        db = get_db()

        # 1. Job must exist in the database
        job = db.execute("SELECT * FROM jobs WHERE canonical_id = ?", (canonical_id,)).fetchone()
        if not job:
            return PolicyResult(False, "Job not found in database")

        # 2. Job must have been evaluated
        decision = db.execute(
            "SELECT * FROM decisions WHERE canonical_id = ? ORDER BY created_at DESC LIMIT 1",
            (canonical_id,)
        ).fetchone()
        if not decision:
            return PolicyResult(False, "Job has not been evaluated")

        if decision["decision"] != "match":
            return PolicyResult(False, f"Job evaluation was '{decision['decision']}', not 'match'")

        # 3. Confidence threshold
        if decision["confidence"] < self.min_confidence:
            return PolicyResult(False, f"Confidence {decision['confidence']} below threshold {self.min_confidence}")

        # 4. Rate limit
        today_count = NotificationRepository.count_today()
        if today_count >= self.max_notifications_per_day:
            return PolicyResult(False, f"Daily notification limit ({self.max_notifications_per_day}) reached")

        # 5. Duplicate notification
        if JobRepository.is_notified(canonical_id):
            return PolicyResult(False, "Job already notified")

        # 6. Target company
        target_companies = self._config.get("target_companies", [])
        if company and target_companies:
            if not any(tc.lower() in company.lower() or company.lower() in tc.lower()
                       for tc in target_companies):
                return PolicyResult(False, f"Company '{company}' not in target list")

        # 7. Excluded roles in title
        exclude_roles = self._config.get("exclude_roles", [])
        title_lower = title.lower()
        for role in exclude_roles:
            if role.lower() in title_lower:
                return PolicyResult(False, f"Excluded role '{role}' in title")

        # 8. Excluded levels
        exclude_levels = self._config.get("exclude_levels", [])
        for level in exclude_levels:
            if level.lower() in title_lower:
                return PolicyResult(False, f"Excluded level '{level}' in title")

        # 9. Location validation — look up from DB sources
        sources = db.execute(
            "SELECT location, description FROM job_sources WHERE canonical_id = ?",
            (canonical_id,)
        ).fetchall()
        for src in sources:
            loc_text = f"{src['location']} {src['description'][:500]}"
            if loc_text.strip() and not self.is_valid_location(loc_text):
                return PolicyResult(False, f"Location validation failed for {canonical_id}")

        return PolicyResult(True, "All checks passed")

    def is_valid_location(self, description: str) -> bool:
        """Check if job location is acceptable. Static method for reuse."""
        text = description[:500]
        for pattern in _REJECT_LOCATIONS:
            if re.search(pattern, text, re.IGNORECASE):
                return False
        for pattern in _ACCEPT_LOCATIONS:
            if re.search(pattern, text, re.IGNORECASE):
                return True
        return True  # Conservative: no location = allow
