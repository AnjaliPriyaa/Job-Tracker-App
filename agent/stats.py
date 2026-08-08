"""Run statistics collector for agent observability."""

import logging
import time
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class RunStats:
    """Tracks per-run statistics for observability and debugging."""

    run_id: str = ""
    started_at: float = field(default_factory=time.monotonic)

    # Search metrics
    queries_generated: int = 0
    searches_executed: int = 0
    sources_searched: set[str] = field(default_factory=set)
    companies_discovered: set[str] = field(default_factory=set)

    # Job metrics
    raw_jobs_found: int = 0
    jobs_normalized: int = 0
    duplicates_removed: int = 0
    jobs_evaluated: int = 0

    # Decision metrics
    jobs_matched: int = 0
    jobs_rejected: int = 0
    jobs_investigated: int = 0

    # Notification metrics
    notifications_sent: int = 0
    notifications_blocked: int = 0

    # Error metrics
    tool_errors: int = 0
    search_failures: int = 0

    def record_search(self, source: str, job_count: int, error: bool = False) -> None:
        self.searches_executed += 1
        if source:
            self.sources_searched.add(source)
        self.raw_jobs_found += job_count
        if error:
            self.search_failures += 1

    def record_company(self, company: str) -> None:
        if company:
            self.companies_discovered.add(company)

    def record_evaluation(self, decision: str) -> None:
        self.jobs_evaluated += 1
        if decision == "match":
            self.jobs_matched += 1
        elif decision == "reject":
            self.jobs_rejected += 1
        elif decision == "investigate":
            self.jobs_investigated += 1

    def record_notification(self, allowed: bool) -> None:
        if allowed:
            self.notifications_sent += 1
        else:
            self.notifications_blocked += 1

    def summary(self) -> dict:
        elapsed = time.monotonic() - self.started_at
        return {
            "run_id": self.run_id,
            "runtime_seconds": round(elapsed, 1),
            "searches": self.searches_executed,
            "sources": sorted(self.sources_searched),
            "companies_found": len(self.companies_discovered),
            "raw_jobs": self.raw_jobs_found,
            "duplicates": self.duplicates_removed,
            "evaluated": self.jobs_evaluated,
            "matched": self.jobs_matched,
            "rejected": self.jobs_rejected,
            "investigated": self.jobs_investigated,
            "notified": self.notifications_sent,
            "blocked": self.notifications_blocked,
            "errors": self.tool_errors,
        }

    def print_summary(self) -> None:
        s = self.summary()
        logger.info("=" * 50)
        logger.info("📊 RUN STATISTICS")
        logger.info("=" * 50)
        logger.info("  Searches:    %d across %d sources %s",
                    s["searches"], len(s["sources"]), s["sources"])
        logger.info("  Companies:   %d discovered", s["companies_found"])
        logger.info("  Jobs:        %d raw → %d after dedup → %d evaluated",
                    s["raw_jobs"], s["raw_jobs"] - s["duplicates"], s["evaluated"])
        logger.info("  Decisions:   %d matched | %d rejected | %d investigated",
                    s["matched"], s["rejected"], s["investigated"])
        logger.info("  Notifications: %d sent | %d blocked", s["notified"], s["blocked"])
        logger.info("  Errors:      %d", s["errors"])
        logger.info("  Runtime:     %.1fs", s["runtime_seconds"])
        logger.info("=" * 50)
