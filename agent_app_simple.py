"""
Main application entry-point for the Company Tracking job monitor.

Provides the AgenticJobTracker class that orchestrates the full pipeline:

    load config → scrape jobs → pre-filter → AI match → notify → track

Run directly:
    python agent_app_simple.py
"""

import json
import logging
import sys
from datetime import datetime, timezone

from langchain_ai import JobMatcher
from langchain_tools import (
    get_job_description,
    manage_seen_jobs,
    scrape_jobs,
    send_telegram,
)
from utils import (
    check_and_cleanup,
    load_config,
    load_seen_jobs,
    mark_job_seen,
    save_seen_jobs,
)

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("agent_app_simple")


# ---------------------------------------------------------------------------
# AgenticJobTracker
# ---------------------------------------------------------------------------

class AgenticJobTracker:
    """
    Autonomous job tracker that scrapes LinkedIn, filters with rules + AI,
    and notifies via Telegram.
    """

    def __init__(self):
        # --- Config ---
        self.config = load_config()

        # --- AI Matcher ---
        self.matcher = JobMatcher()

        # --- State ---
        self.seen_jobs = load_seen_jobs()

        # --- Stats ---
        self.stats = {
            "portals_searched": 0,
            "jobs_scraped": 0,
            "jobs_matched": 0,
            "jobs_notified": 0,
            "errors": 0,
            "started_at": datetime.now(timezone.utc).isoformat(),
        }

        logger.info("AgenticJobTracker initialized — %d target companies, %d roles",
                     len(self.config.get("target_companies", [])),
                     len(self.config.get("roles", [])))

    # ------------------------------------------------------------------
    def run(self) -> dict:
        """Execute the full job-search pipeline.  Returns stats dict."""
        logger.info("=== Starting job search pipeline ===")

        # 1. Periodic cleanup
        if check_and_cleanup():
            logger.info("🧹 Cleanup: cleared seen-jobs history (10-day cycle)")
            self.seen_jobs = set()

        # 2. Iterate over configured job portals
        portals = self.config.get("job_portals", [])
        if not portals:
            logger.warning("No job portals configured — add entries to config.json")
            return self.stats

        target_companies = self.config.get("target_companies", [])
        exclude_roles = self.config.get("exclude_roles", [])
        exclude_levels = self.config.get("exclude_levels", [])
        exclude_keywords = self.config.get("exclude_keywords", [])
        max_experience = self.config.get("experience_years", 6)
        min_experience = self.config.get("min_experience_years", 4)

        for portal in portals:
            self.stats["portals_searched"] += 1
            portal_name = portal.get("name", "Unknown Portal")
            logger.info("Searching: %s", portal_name)

            # --- Scrape ---
            scrape_input = json.dumps({
                "url": portal.get("career_page", ""),
                "target_companies": target_companies,
            })

            try:
                raw = scrape_jobs.invoke({"input_data": scrape_input})
                result = json.loads(raw) if isinstance(raw, str) else raw
            except Exception as e:
                logger.error("Scrape failed for %s: %s", portal_name, e)
                self.stats["errors"] += 1
                continue

            jobs = result.get("jobs", [])
            if result.get("error"):
                logger.warning("Scrape warning: %s", result["error"])

            self.stats["jobs_scraped"] += len(jobs)
            logger.info("  Found %d job cards", len(jobs))

            # --- Process each job ---
            portal_keywords = portal.get("keywords", [])

            for job in jobs:
                try:
                    self._process_job(
                        job,
                        portal_keywords=portal_keywords,
                        target_companies=target_companies,
                        exclude_roles=exclude_roles,
                        exclude_levels=exclude_levels,
                        exclude_keywords=exclude_keywords,
                        max_experience=max_experience,
                        min_experience=min_experience,
                    )
                except Exception as e:
                    logger.error("Error processing job %s: %s", job.get("id", "?"), e)
                    self.stats["errors"] += 1

        # 3. Persist state
        save_seen_jobs(self.seen_jobs)
        self.stats["finished_at"] = datetime.now(timezone.utc).isoformat()

        logger.info("=== Pipeline complete: %d scraped, %d matched, %d notified ===",
                     self.stats["jobs_scraped"], self.stats["jobs_matched"],
                     self.stats["jobs_notified"])

        return self.stats

    # ------------------------------------------------------------------
    def _process_job(
        self,
        job: dict,
        *,
        portal_keywords: list[str],
        target_companies: list[str],
        exclude_roles: list[str],
        exclude_levels: list[str],
        exclude_keywords: list[str],
        max_experience: int,
        min_experience: int,
    ) -> None:
        """Evaluate a single job: check seen → get desc → match → notify."""
        job_id = str(job.get("id", ""))
        title = job.get("title", "")
        company = job.get("company", "")
        url = job.get("url", "")

        # --- Already seen? ---
        if job_id in self.seen_jobs:
            return

        # --- Local pre-filter: excluded roles in title ---
        title_lower = title.lower()
        if any(role in title_lower for role in exclude_roles):
            logger.debug("  ✗ Pre-filtered (excluded role): %s at %s", title, company)
            self.seen_jobs.add(job_id)  # mark seen so we don't re-evaluate
            return

        # --- Local pre-filter: excluded levels in title ---
        if any(level in title_lower for level in exclude_levels):
            logger.debug("  ✗ Pre-filtered (excluded level): %s at %s", title, company)
            self.seen_jobs.add(job_id)
            return

        # --- Fetch description ---
        try:
            raw_desc = get_job_description.invoke({"job_url": url})
            description = raw_desc if isinstance(raw_desc, str) else str(raw_desc)
        except Exception:
            logger.debug("  ⚠ Could not fetch description for %s", job_id)
            self.seen_jobs.add(job_id)
            return

        if description.startswith("ERROR"):
            logger.debug("  ⚠ Description error for %s: %s", job_id, description[:100])
            self.seen_jobs.add(job_id)
            return

        # --- AI Match ---
        match_result = self.matcher.match(
            title=title,
            company=company,
            description=description,
            keywords=portal_keywords,
            target_companies=target_companies,
            exclude_keywords=exclude_keywords,
            exclude_roles=exclude_roles,
            exclude_levels=exclude_levels,
            max_experience=max_experience,
        )

        logger.info("  %s at %s → match=%s (%.0f%%)  %s",
                     title, company, match_result.match,
                     match_result.confidence * 100, match_result.reason)

        # --- Notify if match ---
        if match_result.match and match_result.confidence >= 0.6:
            self.stats["jobs_matched"] += 1

            message = (
                f"🔔 New Job Match!\n\n"
                f"*{title}*\n"
                f"🏢 {company}\n"
                f"🔗 {url}\n\n"
                f"_{match_result.reason}_"
            )
            try:
                send_telegram.invoke({"message": message})
                self.stats["jobs_notified"] += 1
                logger.info("  ✅ Notified: %s at %s", title, company)
            except Exception as e:
                logger.error("  ❌ Telegram send failed: %s", e)

        # --- Mark seen ---
        self.seen_jobs.add(job_id)


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("🤖 Starting Agentic Job Tracker...")
    print(f"   Time: {datetime.now(timezone.utc).isoformat()}")
    print()

    try:
        tracker = AgenticJobTracker()
        stats = tracker.run()

        print()
        print("=" * 50)
        print("📊 Run Summary")
        print("=" * 50)
        print(f"   Portals searched:  {stats['portals_searched']}")
        print(f"   Jobs scraped:      {stats['jobs_scraped']}")
        print(f"   Jobs matched:      {stats['jobs_matched']}")
        print(f"   Notifications:     {stats['jobs_notified']}")
        print(f"   Errors:            {stats['errors']}")
        print()

        if stats["jobs_notified"] > 0:
            print(f"🎉 {stats['jobs_notified']} new job(s) found!")
        else:
            print("😴 No new matching jobs this round.")

    except Exception as e:
        logger.exception("Fatal error in job tracker")
        print(f"❌ Fatal error: {e}")
        sys.exit(1)
