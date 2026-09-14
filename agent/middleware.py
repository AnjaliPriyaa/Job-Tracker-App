"""
Execution budget middleware — physically enforces limits to prevent
runaway agent and tool loops.
"""

import json
import logging
import time
from typing import Any

from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import ToolMessage

logger = logging.getLogger(__name__)

# Module-level budget instance — set during agent build, accessible to tools
_active_budget = None  # type: BudgetTracker | None


def get_budget():
    """Get the active budget tracker for the current agent run."""
    return _active_budget


def set_budget(budget):
    """Set the active budget tracker. Called by agent.py during build."""
    global _active_budget
    _active_budget = budget


class BudgetTracker:
    """Tracks execution budget — physically enforced limits."""

    def __init__(self, max_tool_calls: int = 48, max_searches: int = 12,
                 max_notifications: int = 8, max_investigation_depth: int = 2,
                 max_llm_evaluations: int = 6, timeout_seconds: int = 300):
        self.max_tool_calls = max_tool_calls
        self.max_searches = max_searches
        self.max_notifications = max_notifications
        self.max_investigation_depth = max_investigation_depth
        self.max_llm_evaluations = max_llm_evaluations
        self.timeout_seconds = timeout_seconds
        self.start_time = time.monotonic()
        self.tool_calls = 0
        self.searches = 0
        self.notifications = 0
        self.llm_evaluations = 0
        self.tool_call_counts: dict[str, int] = {}
        self.investigation_depth: dict[str, int] = {}

    def check_tool_call(self, tool_name: str) -> dict | None:
        """Check if a tool call is allowed. Returns None if allowed, error dict if blocked."""
        self.tool_calls += 1
        self.tool_call_counts[tool_name] = self.tool_call_counts.get(tool_name, 0) + 1

        if tool_name in ("search_linkedin", "search_web_jobs", "search_ats",
                         "discover_company_career_page", "discover_ats_platform"):
            self.searches += 1
            if self.searches > self.max_searches:
                return {
                    "blocked": True,
                    "reason": f"Search budget reached ({self.max_searches}).",
                    "searches_used": self.searches,
                }

        if tool_name == "notify_user":
            self.notifications += 1
            if self.notifications > self.max_notifications:
                return {
                    "blocked": True,
                    "reason": f"Notification budget reached ({self.max_notifications}).",
                    "notifications_used": self.notifications,
                }

        if self.tool_calls > self.max_tool_calls:
            return {
                "blocked": True,
                "reason": f"Tool call budget exceeded ({self.max_tool_calls}).",
                "tool_calls_used": self.tool_calls,
            }

        elapsed = time.monotonic() - self.start_time
        if elapsed > self.timeout_seconds:
            return {
                "blocked": True,
                "reason": f"Execution timeout ({self.timeout_seconds}s) reached.",
                "elapsed_seconds": int(elapsed),
            }

        return None

    def check_llm_evaluation(self) -> dict | None:
        """Reserve one nested LLM evaluation, falling back locally when exhausted."""
        self.llm_evaluations += 1
        if self.llm_evaluations > self.max_llm_evaluations:
            return {
                "blocked": True,
                "reason": f"LLM evaluation budget reached ({self.max_llm_evaluations}).",
            }
        return None

    def check_investigation(self, canonical_id: str) -> dict | None:
        """Check if investigation depth is exceeded for a specific job."""
        depth = self.investigation_depth.get(canonical_id, 0) + 1
        self.investigation_depth[canonical_id] = depth
        if depth > self.max_investigation_depth:
            return {
                "blocked": True,
                "reason": f"Investigation depth ({self.max_investigation_depth}) exceeded.",
                "depth": depth,
            }
        return None


class BudgetMiddleware(AgentMiddleware):
    """
    Middleware that wraps tool calls with emergency budget enforcement.

    Enforces: max tool calls, max searches, max notifications, timeout.
    Investigation depth is enforced by evaluate_job tool via get_budget().
    """

    def __init__(self, budget: BudgetTracker | None = None):
        super().__init__()
        self.budget = budget or BudgetTracker()

    def wrap_tool_call(
        self,
        request: Any,
        handler: Any,
    ) -> Any:
        """Intercept tool calls and enforce budget limits."""
        tool_call = getattr(request, "tool_call", None)
        if isinstance(tool_call, dict):
            tool_name = tool_call.get("name", "unknown")
        else:
            tool_name = getattr(request, "name", "unknown")
        block = self.budget.check_tool_call(tool_name)
        if block:
            logger.info("BudgetMiddleware BLOCK: %s — %s", tool_name, block["reason"])
            return ToolMessage(
                content=json.dumps(block),
                tool_call_id=(tool_call or {}).get("id", "budget-block"),
                name=tool_name,
                status="error",
            )
        return handler(request)
