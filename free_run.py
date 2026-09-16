#!/usr/bin/env python3
"""Bounded, key-free search run using the real search and Telegram path.

The LLM-driven agent remains in agent.py; this entry point uses its
existing tools and policy rules without contacting any model provider.
"""

import json
import logging
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path

from agent.middleware import BudgetTracker, set_budget
from policies.job_policy import is_target_company
from storage import AgentRunRepository, JobRepository
from tools.discovery_tools import discover_company_career_page
from tools.evaluation_tools import evaluate_job
from tools.job_tools import fetch_job
from tools.notification_tools import notify_user
from tools.search_tools import search_ats, search_company_careers, search_linkedin
from tools.state_tools import record_decision
from storage.database import get_db

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("free_run")

TARGET_TITLE = re.compile(
    r"\b(?:devops|devsecops|sre)\b|"
    r"\b(?:site reliability|service reliability|platform|cloud|infrastructure|cloud security)\s+engineer\b|"
    r"\bsoftware engineer\s*[,–-]\s*(?:infrastructure|cloud|platform)\b",
    re.IGNORECASE,
)


def _number(name: str, default: int, maximum: int) -> int:
    try:
        return min(max(1, int(os.getenv(name, default))), maximum)
    except ValueError:
        return default


def _call(tool, args: dict, budget: BudgetTracker) -> dict:
    block = budget.check_tool_call(tool.name)
    if block:
        logger.warning("%s skipped: %s", tool.name, block["reason"])
        return {"error": block["reason"], "results": []}
    try:
        return json.loads(tool.invoke(args))
    except Exception as exc:
        logger.warning("%s failed: %s", tool.name, exc)
        return {"error": str(exc), "results": []}


def _pending(context: str, limit: int) -> list[dict]:
    source_filter = {
        "linkedin": "linkedin", "career": "company_career", "ats": "ats%",
    }[context]
    rows = get_db().execute(
        """SELECT s.canonical_id, s.source, s.source_job_id, s.url,
                  s.title, s.company, s.location
           FROM job_sources AS s JOIN jobs AS j USING (canonical_id)
           WHERE j.status IN ('discovered', 'investigating', 'match')
             AND s.source LIKE ?
           ORDER BY CASE WHEN j.status = 'match' THEN 0 ELSE 1 END,
                    j.last_seen DESC LIMIT ?""",
        (source_filter, limit),
    ).fetchall()
    return [dict(row) for row in rows]


def _career_companies(config: dict, limit: int, day: int | None = None,
                      available: set[str] | None = None,
                      last_attempted: dict[str, str] | None = None) -> list[str]:
    companies = config.get("target_companies", [])
    if available is not None:
        companies = [name for name in companies if name in available]
    if not companies:
        return []
    priority = [name.strip() for name in os.getenv("FREE_CAREER_PRIORITY", "").split(",")
                if name.strip() in companies]
    priority = list(dict.fromkeys(priority))[:limit]
    remaining = [name for name in companies if name not in priority]
    if not remaining:
        return priority
    if last_attempted is not None:
        # Persistent source memory gives never-searched or overdue companies
        # the next slots; a short run cannot silently skip them forever.
        remaining.sort(key=lambda name: last_attempted.get(name, ""))
        return priority + remaining[:max(0, limit - len(priority))]
    if day is None:
        day = datetime.now(timezone.utc).date().toordinal()
    rotating_slots = limit - len(priority)
    start = ((day - 1) * rotating_slots) % len(remaining)
    return priority + [remaining[(start + offset) % len(remaining)]
                       for offset in range(min(rotating_slots, len(remaining)))]


def _career_attempts() -> dict[str, str]:
    rows = get_db().execute(
        "SELECT company, last_attempted_at FROM career_source_state"
    ).fetchall()
    return {row["company"]: row["last_attempted_at"] for row in rows}


def _remember_career_source(company: str, payload: dict) -> None:
    error = str(payload.get("error") or "")
    if error.startswith("No relevant India jobs"):
        error = ""
    db = get_db()
    db.execute(
        """INSERT INTO career_source_state
           (company, last_attempted_at, last_new_count, consecutive_failures, last_error)
           VALUES (?, ?, ?, ?, ?)
           ON CONFLICT(company) DO UPDATE SET
             last_attempted_at = excluded.last_attempted_at,
             last_new_count = excluded.last_new_count,
             consecutive_failures = CASE WHEN excluded.last_error = '' THEN 0
               ELSE career_source_state.consecutive_failures + 1 END,
             last_error = excluded.last_error""",
        (company, datetime.now(timezone.utc).isoformat(),
         int(payload.get("new_count", 0)), int(bool(error)), error[:300]),
    )
    db.commit()


def _discover(context: str, config: dict, budget: BudgetTracker,
              max_candidates: int) -> list[dict]:
    if context == "linkedin":
        portals = config.get("job_portals", [])
        url = next((p.get("career_page", "") for p in portals if p.get("is_linkedin")), "")
        if not url:
            raise RuntimeError("No LinkedIn search URL is configured")
        payload = _call(search_linkedin, {"url": url, "max_results": max_candidates}, budget)
        logger.info("LinkedIn: %d new, %d duplicates, error=%s",
                    payload.get("new_count", 0), payload.get("duplicates_filtered", 0),
                    payload.get("error"))
        return payload.get("results", [])

    candidates = []
    company_limit = _number("FREE_MAX_COMPANIES", 18 if context == "career" else 6, 24)
    available = None
    if context == "career":
        knowledge_path = Path(__file__).resolve().parent / "career_knowledge.json"
        available = set(json.loads(knowledge_path.read_text()))
        available.update(config.get("company_career_pages", {}))
    attempts = _career_attempts() if context == "career" else None
    for company in _career_companies(config, company_limit, available=available,
                                     last_attempted=attempts):
        if time.monotonic() - budget.start_time > budget.timeout_seconds:
            break
        per_company = min(_number("FREE_RESULTS_PER_COMPANY", 2 if context == "career" else 4, 12),
                          max_candidates - len(candidates))
        if context == "career":
            payload = _call(search_company_careers, {
                "company": company, "max_results": per_company,
            }, budget)
            _remember_career_source(company, payload)
            logger.info("%s first-party: %d new, %d duplicates, error=%s", company,
                        payload.get("new_count", 0), payload.get("duplicates_filtered", 0),
                        payload.get("error"))
            candidates.extend(payload.get("results", []))
            if len(candidates) >= max_candidates:
                break
            continue

        discovered = _call(discover_company_career_page, {"company": company}, budget)
        if not discovered.get("found"):
            logger.info("No supported career board for %s", company)
            continue
        payload = _call(search_ats, {
            "company": company,
            "ats_url": discovered["career_page_url"],
            "max_results": per_company,
        }, budget)
        logger.info("%s: %d new, %d duplicates, error=%s", company,
                    payload.get("new_count", 0), payload.get("duplicates_filtered", 0),
                    payload.get("error"))
        candidates.extend(payload.get("results", []))
        if len(candidates) >= max_candidates:
            break
    return candidates[:max_candidates]


def _process(candidate: dict, budget: BudgetTracker,
             target_companies: list[str] | None = None) -> bool:
    canonical_id = candidate.get("canonical_id", "")
    url = candidate.get("url", "")
    if not canonical_id or not url or JobRepository.is_notified(canonical_id):
        return False
    title_hint = candidate.get("title", "")
    company_hint = candidate.get("company", "")
    if target_companies and company_hint and not is_target_company(company_hint, target_companies):
        return False
    if title_hint and not TARGET_TITLE.search(title_hint):
        return False

    stored = get_db().execute(
        "SELECT description FROM job_sources WHERE canonical_id = ? AND source = ? LIMIT 1",
        (canonical_id, candidate.get("source", "")),
    ).fetchone()
    if stored and len(stored["description"] or "") >= 120 and title_hint and candidate.get("company"):
        details = {"title": title_hint, "company": candidate["company"],
                   "location": candidate.get("location", ""),
                   "description": stored["description"]}
    else:
        details = _call(fetch_job, {"url": url, "source": candidate.get("source", "generic")}, budget)
        if details.get("error"):
            logger.info("Skipping %s: %s", url, details["error"])
            return False
    title = details.get("title") or title_hint
    company = details.get("company") or candidate.get("company", "")
    location = details.get("location") or candidate.get("location", "")
    description = details.get("description", "")
    if not title or not company or not description or not TARGET_TITLE.search(title):
        logger.info("Skipping incomplete or unrelated listing: %s", url)
        return False

    JobRepository.upsert(
        canonical_id, company, title, location,
        candidate.get("source", "web"), candidate.get("source_job_id", url),
        url, description,
    )
    result = _call(evaluate_job, {
        "title": title, "company": company, "description": description,
        "location": location, "canonical_id": canonical_id,
    }, budget)
    decision = result.get("decision")
    if decision not in {"match", "reject", "investigate"}:
        return False
    _call(record_decision, {
        "canonical_id": canonical_id, "decision": decision,
        "score": result.get("score", 0), "confidence": result.get("confidence", 0),
        "reasons": result.get("reasons", []),
    }, budget)
    logger.info("%s: %s at %s (%s)", decision, title, company, result.get("evaluation_mode"))
    if decision != "match":
        return False
    reason = "; ".join(result.get("reasons", []))
    notification = _call(notify_user, {
        "canonical_id": canonical_id, "title": title,
        "company": company, "url": url, "reason": reason,
    }, budget)
    if not notification.get("notified"):
        logger.info("Telegram skipped: %s", notification.get("error"))
    return bool(notification.get("notified"))


def main() -> None:
    context = os.getenv("RUN_CONTEXT", "linkedin").lower()
    if context not in {"linkedin", "career", "ats"}:
        raise ValueError("RUN_CONTEXT must be 'linkedin', 'career', or 'ats'")
    os.environ["AI_PROVIDER"] = "rules"  # Never call DeepSeek or Gemini in this mode.
    config = json.loads((Path(__file__).resolve().parent / "config.json").read_text())
    if context == "career":
        verified = set(config.get("company_career_pages", {})) & set(config.get("target_companies", []))
        knowledge = json.loads((Path(__file__).resolve().parent / "career_knowledge.json").read_text())
        logger.info("Career knowledge: %d/%d company domains; %d custom verified adapters",
                    len(set(knowledge) & set(config.get("target_companies", []))),
                    len(config.get("target_companies", [])), len(verified))
    budget = BudgetTracker(
        max_tool_calls=72, max_searches=24,
        max_notifications=_number("MAX_NOTIFICATIONS", 1, 8),
        max_llm_evaluations=0, timeout_seconds=300,
    )
    set_budget(budget)
    run_id = f"rules_{context}_{os.getenv('GITHUB_RUN_ID') or datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}"
    AgentRunRepository.start(run_id, context, "rules/no-llm")
    status, error, sent = "completed", "", 0
    max_candidates = _number("FREE_MAX_CANDIDATES", 12, 25)
    try:
        fresh = _discover(context, config, budget, max_candidates)
        pending = _pending(context, max_candidates)
        unique = {item["canonical_id"]: item for item in [*fresh, *pending] if item.get("canonical_id")}
        logger.info("%s: %d candidates to inspect", context, len(unique))
        for candidate in list(unique.values())[:max_candidates]:
            if time.monotonic() - budget.start_time > budget.timeout_seconds:
                logger.warning("Run time budget reached")
                break
            sent += _process(candidate, budget, config.get("target_companies", []))
            if sent >= budget.max_notifications:
                break
    except Exception as exc:
        status, error = "error", str(exc)
        logger.exception("Key-free run failed")
        raise
    finally:
        AgentRunRepository.finish(run_id, budget, {
            "llm_calls": 0, "evaluation_llm_calls": 0,
            "input_tokens": 0, "output_tokens": 0,
            "total_tokens": 0, "cached_input_tokens": 0,
        }, status, error)
        # Actions commits the SQLite file in the next step, not its WAL sidecar.
        # Flush this run's source memory and job state into the tracked file.
        checkpoint = get_db().execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
        if checkpoint and checkpoint[0]:
            logger.warning("SQLite checkpoint was busy; state may not be in the tracked DB")
        logger.info("Run finished: status=%s, searches=%d, tools=%d, Telegram sent=%d, model tokens=0",
                    status, budget.searches, budget.tool_calls, sent)


if __name__ == "__main__":
    main()
