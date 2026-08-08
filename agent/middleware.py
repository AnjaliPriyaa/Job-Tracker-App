"""
Emergency budget middleware — prevents only pathological situations.

This is NOT a search/workflow limiter. The agent should search
comprehensively. This only stops truly runaway agents (infinite loops,
extreme recursion, hours-long execution).
"""

import json
import logging
import time
from typing import Any

logger = logging.getLogger(__name__)


class BudgetTracker:
    """Tracks execution for emergency protection only — no search limits."""

    def __init__(self, max_tool_calls: int = 500, timeout_seconds: int = 600):
        self.max_tool_calls = max_tool_calls
        self.timeout_seconds = timeout_seconds
        self.start_time = time.monotonic()
        self.tool_calls = 0
        self.searches = 0
        self.notifications = 0

    def check_tool_call(self, tool_name: str) -> dict | None:
        """Only block in true emergency: excessive calls or timeout."""
        self.tool_calls += 1

        if tool_name in ("search_linkedin", "search_web_jobs", "search_ats"):
            self.searches += 1
        if tool_name == "notify_user":
            self.notifications += 1

        if self.tool_calls > self.max_tool_calls:
            return {
                "blocked": True,
                "reason": f"Emergency stop: {self.max_tool_calls} tool calls reached. Stopping.",
                "tool_calls_used": self.tool_calls,
            }

        elapsed = time.monotonic() - self.start_time
        if elapsed > self.timeout_seconds:
            return {
                "blocked": True,
                "reason": f"Emergency stop: timeout ({self.timeout_seconds}s) reached.",
                "elapsed_seconds": int(elapsed),
            }

        return None


class BudgetMiddleware:
    """Wraps tool calls with emergency budget protection only."""

    def __init__(self, budget: BudgetTracker | None = None):
        self.budget = budget or BudgetTracker()

    def wrap_tool_call(self, request: Any, handler: Any):
        tool_name = getattr(request, "name", "unknown") if hasattr(request, "name") else str(request)
        block = self.budget.check_tool_call(tool_name)
        if block:
            logger.info("BudgetMiddleware BLOCK: %s — %s", tool_name, block["reason"])
            return json.dumps(block)
        return handler(request)

