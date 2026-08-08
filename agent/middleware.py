"""
Execution budget middleware — physically prevents runaway agents.

Enforces limits on tool calls, searches, and notifications.
The agent receives structured feedback when limits are reached,
allowing it to gracefully stop.
"""

import json
import logging
import time
from typing import Any

from langgraph.prebuilt.tool_node import ToolNode

logger = logging.getLogger(__name__)


class BudgetTracker:
    """Tracks execution budget consumption across an agent run."""

    def __init__(self, max_tool_calls: int = 80, max_searches: int = 8,
                 max_notifications: int = 15, max_investigation_depth: int = 3,
                 timeout_seconds: int = 600):
        self.max_tool_calls = max_tool_calls
        self.max_searches = max_searches
        self.max_notifications = max_notifications
        self.max_investigation_depth = max_investigation_depth
        self.timeout_seconds = timeout_seconds
        self.start_time = time.monotonic()

        self.tool_calls = 0
        self.searches = 0
        self.notifications = 0
        self.investigation_depth: dict[str, int] = {}

    def check_tool_call(self, tool_name: str) -> dict | None:
        """Check if a tool call is allowed. Returns None if allowed, error dict if blocked."""
        self.tool_calls += 1

        # Overall tool call limit
        if self.tool_calls > self.max_tool_calls:
            return {
                "blocked": True,
                "reason": f"Tool call limit ({self.max_tool_calls}) exceeded. Stop and report results.",
                "tool_calls_used": self.tool_calls,
            }

        # Search limit
        if tool_name in ("search_linkedin", "search_web_jobs", "search_ats"):
            self.searches += 1
            if self.searches > self.max_searches:
                return {
                    "blocked": True,
                    "reason": f"Search limit ({self.max_searches}) reached. Use results gathered so far.",
                    "searches_used": self.searches,
                }

        # Notification limit
        if tool_name == "notify_user":
            self.notifications += 1
            if self.notifications > self.max_notifications:
                return {
                    "blocked": True,
                    "reason": f"Notification limit ({self.max_notifications}) reached.",
                    "notifications_used": self.notifications,
                }

        # Timeout
        elapsed = time.monotonic() - self.start_time
        if elapsed > self.timeout_seconds:
            return {
                "blocked": True,
                "reason": f"Execution timeout ({self.timeout_seconds}s) reached.",
                "elapsed_seconds": int(elapsed),
            }

        return None

    def check_investigation(self, canonical_id: str) -> dict | None:
        """Check if investigation depth limit is exceeded."""
        depth = self.investigation_depth.get(canonical_id, 0) + 1
        self.investigation_depth[canonical_id] = depth
        if depth > self.max_investigation_depth:
            return {
                "blocked": True,
                "reason": f"Investigation depth ({self.max_investigation_depth}) exceeded for {canonical_id}.",
                "depth": depth,
            }
        return None


class BudgetMiddleware:
    """
    Middleware that wraps tool calls with budget enforcement.
    When a tool call exceeds the budget, it returns a structured error
    instead of executing, allowing the agent to gracefully stop.
    """

    def __init__(self, budget: BudgetTracker | None = None):
        self.budget = budget or BudgetTracker()

    def wrap_tool_call(self, request: Any, handler: Any):
        """Intercept tool calls and enforce budget."""
        tool_name = getattr(request, "name", "unknown") if hasattr(request, "name") else str(request)

        # Check budget
        block = self.budget.check_tool_call(tool_name)
        if block:
            logger.info("BudgetMiddleware BLOCK: %s — %s", tool_name, block["reason"])
            return json.dumps(block)

        return handler(request)
