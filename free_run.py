#!/usr/bin/env python3
"""Bounded, key-free search run for testing the real search and Telegram path.

The LLM-driven agent remains in agent.py; this temporary entry point uses its
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
from storage import AgentRunRepository, JobRepository
from tools.discovery_tools import discover_company_career_page
from tools.evaluation_tools import evaluate_job
from tools.job_tools import fetch_job
from tools.notification_tools import notify_user
from tools.search_tools import search_ats, search_linkedin
from tools.state_tools import record_decision
from storage.database import get_db

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("free_run")

TARGET_TITLE = re.compile(
    r"\b(?:devops|devsecops|sre)\b|"
    r"\b(?:site reliability|platform|cloud|infrastructure|cloud security)\s+engineer\b",
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
    source_filter = "linkedin" if context == "linkedin" else "ats%"
    rows = get_db().execute(
        """SELECT s.canonical_id, s.source, s.source_job_id, s.url,
                  s.title, s.company, s.location
           FROM job_sources AS s JOIN jobs AS j USING (canonical_id)
           WHERE j.status IN ('discovered', 'investigating') AND s.source LIKE ?
           ORDER BY j.last_seen DESC LIMIT ?""",
        (source_filter, limit),
    ).fetchall()
    return [dict(row) for row in rows]


def _career_companies(config: dict, limit: int, day: int | None = None) -> list[str]:
    companies = config.get("target_companies", [])
    if not companies:
        return []
    priority = [name.strip() for name in os.getenv("FREE_CAREER_PRIORITY", "").split(",")
                if name.strip() in companies]
    priority = list(dict.fromkeys(priority))[:limit]
    remaining = [name for name in companies if name not in priority]
    if not remaining:
        return priority
    if day is None:
        day = datetime.now(timezone.utc).date().toordinal()
    rotating_slots = limit - len(priority)
    start = ((day - 1) * rotating_slots) % len(remaining)
    return priority + [remaining[(start + offset) % len(remaining)]
                       for offset in range(min(rotating_slots, len(remaining)))]


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
    company_limit = _number("FREE_MAX_COMPANIES", 6, 12)
    for company in _career_companies(config, company_limit):
        if time.monotonic() - budget.start_time > budget.timeout_seconds:
            break
        discovered = _call(discover_company_career_page, {"company": company}, budget)
        if not discovered.get("found"):
            logger.info("No supported career board for %s", company)
            continue
        per_company = min(_number("FREE_RESULTS_PER_COMPANY", 4, 12),
                          max_candidates - len(candidates))
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


def _process(candidate: dict, budget: BudgetTracker) -> bool:
    canonical_id = candidate.get("canonical_id", "")
    url = candidate.get("url", "")
    if not canonical_id or not url or JobRepository.is_notified(canonical_id):
        return False
    title_hint = candidate.get("title", "")
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
    if context not in {"linkedin", "career"}:
        raise ValueError("RUN_CONTEXT must be 'linkedin' or 'career'")
    os.environ["AI_PROVIDER"] = "rules"  # Never call DeepSeek or Gemini in this mode.
    config = json.loads((Path(__file__).resolve().parent / "config.json").read_text())
    budget = BudgetTracker(
        max_tool_calls=48, max_searches=12,
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
            sent += _process(candidate, budget)
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
        logger.info("Run finished: status=%s, searches=%d, tools=%d, Telegram sent=%d, model tokens=0",
                    status, budget.searches, budget.tool_calls, sent)


if __name__ == "__main__":
    main()
