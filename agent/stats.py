"""Run statistics collector for agent observability."""

import logging
import threading
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.messages import AIMessage

logger = logging.getLogger(__name__)


class TokenUsageTracker(BaseCallbackHandler):
    """Collect provider-reported token usage for one complete agent run."""

    def __init__(self) -> None:
        super().__init__()
        self._lock = threading.Lock()
        self.llm_calls = 0
        self.evaluation_llm_calls = 0
        self.input_tokens = 0
        self.output_tokens = 0
        self.total_tokens = 0
        self.cached_input_tokens = 0
        self.calls_by_model: dict[str, int] = defaultdict(int)

    def on_llm_end(self, response: Any, *, tags: list[str] | None = None, **kwargs: Any) -> None:
        usage: dict[str, Any] = {}
        model_name = "unknown"
        try:
            message = response.generations[0][0].message
            if isinstance(message, AIMessage):
                usage = dict(message.usage_metadata or {})
                model_name = message.response_metadata.get("model_name", model_name)
        except (AttributeError, IndexError, TypeError):
            pass

        llm_output = getattr(response, "llm_output", None) or {}
        if not usage:
            usage = dict(llm_output.get("token_usage") or llm_output.get("usage") or {})
        model_name = llm_output.get("model_name", model_name)

        input_tokens = int(usage.get("input_tokens", usage.get("prompt_tokens", 0)) or 0)
        output_tokens = int(usage.get("output_tokens", usage.get("completion_tokens", 0)) or 0)
        total_tokens = int(usage.get("total_tokens", input_tokens + output_tokens) or 0)
        input_details = usage.get("input_token_details") or {}
        cached_tokens = int(
            input_details.get("cache_read", 0)
            or usage.get("prompt_cache_hit_tokens", 0)
            or 0
        )

        with self._lock:
            self.llm_calls += 1
            if "evaluation" in (tags or []):
                self.evaluation_llm_calls += 1
            self.input_tokens += input_tokens
            self.output_tokens += output_tokens
            self.total_tokens += total_tokens
            self.cached_input_tokens += cached_tokens
            self.calls_by_model[model_name] += 1

    def summary(self) -> dict[str, Any]:
        return {
            "llm_calls": self.llm_calls,
            "evaluation_llm_calls": self.evaluation_llm_calls,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "total_tokens": self.total_tokens,
            "cached_input_tokens": self.cached_input_tokens,
            "calls_by_model": dict(self.calls_by_model),
        }


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

    llm_calls: int = 0
    evaluation_llm_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    cached_input_tokens: int = 0

    def apply_runtime_metrics(self, budget: Any, usage: TokenUsageTracker) -> None:
        """Copy enforced counters and provider-reported tokens into this run."""
        token_summary = usage.summary()
        self.searches_executed = budget.searches
        self.notifications_sent = budget.notifications
        self.jobs_evaluated = budget.tool_call_counts.get("evaluate_job", 0)
        self.llm_calls = token_summary["llm_calls"]
        self.evaluation_llm_calls = token_summary["evaluation_llm_calls"]
        self.input_tokens = token_summary["input_tokens"]
        self.output_tokens = token_summary["output_tokens"]
        self.total_tokens = token_summary["total_tokens"]
        self.cached_input_tokens = token_summary["cached_input_tokens"]

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
            "llm_calls": self.llm_calls,
            "evaluation_llm_calls": self.evaluation_llm_calls,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "total_tokens": self.total_tokens,
            "cached_input_tokens": self.cached_input_tokens,
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
        logger.info("  LLM:         %d calls (%d nested evaluations)",
                    s["llm_calls"], s["evaluation_llm_calls"])
        logger.info("  Tokens:      %d input | %d output | %d total | %d cached input",
                    s["input_tokens"], s["output_tokens"], s["total_tokens"],
                    s["cached_input_tokens"])
        logger.info("  Runtime:     %.1fs", s["runtime_seconds"])
        logger.info("=" * 50)
