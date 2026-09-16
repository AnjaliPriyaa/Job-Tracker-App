#!/usr/bin/env python3
"""
Agentic Multi-Source Job Tracker.

Single entry point. Uses a bounded LangChain agent loop with typed tools,
SQLite state, policy enforcement, and execution budgets.

The LLM agent decides what to do — there is no hard-coded workflow.

Usage:
    python agent.py
"""

import logging
import os
import sys
import time
from datetime import datetime, timezone

from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("agent")


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        logger.warning("Invalid %s; using %d", name, default)
        return default


def _selected_provider() -> str:
    """Use Gemini unless DeepSeek is explicitly re-enabled."""
    provider = os.getenv("AI_PROVIDER", "gemini").strip().lower()
    if provider not in {"gemini", "deepseek"}:
        raise ValueError("AI_PROVIDER must be 'gemini' or 'deepseek'")
    key_name = "GEMINI_API_KEY" if provider == "gemini" else "DEEPSEEK_API_KEY"
    if not os.getenv(key_name):
        raise RuntimeError(f"{key_name} is required for AI_PROVIDER={provider}")
    return provider

# ---------------------------------------------------------------------------
# Build the agent
# ---------------------------------------------------------------------------


def build_agent():
    """Create the agentic job search agent."""
    from langchain_openai import ChatOpenAI
    from langchain.agents import create_agent
    from langchain.agents.middleware import (
        ClearToolUsesEdit, ContextEditingMiddleware, ModelCallLimitMiddleware,
    )

    from tools import ALL_TOOLS
    from agent.prompts import SYSTEM_PROMPT
    from agent.middleware import BudgetMiddleware, BudgetTracker, set_budget

    # Model
    provider = _selected_provider()

    if provider == "deepseek":
        model = ChatOpenAI(
            model=os.getenv("DEEPSEEK_MODEL", "deepseek-chat"),
            temperature=0.1,
            max_tokens=_env_int("AGENT_MAX_OUTPUT_TOKENS", 700),
            openai_api_key=os.environ["DEEPSEEK_API_KEY"],
            openai_api_base="https://api.deepseek.com",
        )
        logger.info("Model: DeepSeek (%s)", os.getenv("DEEPSEEK_MODEL", "deepseek-chat"))
    else:
        from langchain_google_genai import ChatGoogleGenerativeAI
        model = ChatGoogleGenerativeAI(
            model=os.getenv("GEMINI_MODEL", "gemini-2.5-flash"),
            temperature=0.1,
            max_output_tokens=_env_int("AGENT_MAX_OUTPUT_TOKENS", 700),
            thinking_budget=0,
            google_api_key=os.environ["GEMINI_API_KEY"],
        )
        logger.info("Model: Gemini (%s)", os.getenv("GEMINI_MODEL", "gemini-2.5-flash"))

    # Budget — physically enforced by middleware
    budget = BudgetTracker(
        max_tool_calls=_env_int("MAX_TOOL_CALLS", 48),
        max_searches=_env_int("MAX_SEARCHES", 12),
        max_notifications=_env_int("MAX_NOTIFICATIONS", 8),
        max_investigation_depth=_env_int("MAX_INVESTIGATION_DEPTH", 2),
        max_llm_evaluations=_env_int("MAX_LLM_EVALUATIONS", 6),
        timeout_seconds=_env_int("AGENT_TIMEOUT_SECONDS", 300),
    )
    set_budget(budget)  # Make accessible to tools

    # This task needs an adaptive tool loop, but not DeepAgents' implicit shell,
    # filesystem, todo, or general-purpose subagent. The latter can recursively
    # start another unbudgeted LLM loop. LangChain's base agent preserves the
    # decision-making behavior with a much smaller prompt/tool surface.
    agent = create_agent(
        model=model,
        tools=ALL_TOOLS,
        system_prompt=SYSTEM_PROMPT,
        middleware=[
            ContextEditingMiddleware(edits=[ClearToolUsesEdit(
                trigger=_env_int("CONTEXT_PRUNE_TOKENS", 10_000),
                keep=4,
                clear_tool_inputs=True,
                placeholder="[older tool payload cleared]",
            )]),
            ModelCallLimitMiddleware(
                run_limit=_env_int("MAX_MODEL_CALLS", 14),
                exit_behavior="end",
            ),
            BudgetMiddleware(budget),
        ],
    ).with_config({"recursion_limit": _env_int("AGENT_RECURSION_LIMIT", 40)})

    logger.info("Agent built: %d tools, emergency budget=%d calls/%ds",
                len(ALL_TOOLS), budget.max_tool_calls, budget.timeout_seconds)

    return agent, budget


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    from agent.stats import RunStats, TokenUsageTracker
    from storage import AgentRunRepository

    context = os.getenv("RUN_CONTEXT", "full")

    CONTEXT_MESSAGES = {
        "linkedin": (
            "Your focus: find DevOps, Cloud, SRE, and Platform Engineering jobs matching "
            "the user's preferences. LinkedIn is your primary source — the search URL is "
            "available in the user preferences. You have search, discovery, inspection, "
            "evaluation, and notification tools available. Prioritize new results and "
            "stop after enough strong matches; you decide the approach."
        ),
        "career": (
            "Your focus: find DevOps, Cloud, SRE, and Platform Engineering jobs from "
            "company career pages. You have tools to discover where companies post jobs, "
            "search their ATS platforms, and evaluate candidates. LinkedIn search is also "
            "available as a supplement. You decide which companies to investigate, which "
            "tools to use. Prioritize a small set of likely companies and stop when "
            "additional searches are unlikely to help."
        ),
        "full": (
            "Find DevOps, Cloud, SRE, and Platform Engineering jobs matching the "
            "user's preferences across all available sources. You have a full suite "
            "of search, discovery, inspection, evaluation, and notification tools. "
            "Adapt based on results, favor quality over breadth, and stop when additional "
            "searches are unlikely to help."
        ),
    }

    message = CONTEXT_MESSAGES.get(context, CONTEXT_MESSAGES["full"])

    label = {"linkedin": "LINKEDIN", "career": "CAREER PAGES", "full": "FULL SEARCH"}.get(context, "FULL")
    print("=" * 60)
    print(f"🤖 AGENTIC JOB SEARCH — {label}")
    print("=" * 60)
    print(f"   Start: {datetime.now(timezone.utc).isoformat()}")
    print(f"   Context: {context}")
    print()

    agent, budget = build_agent()
    stats = RunStats(run_id=f"{context}_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}")
    usage = TokenUsageTracker()
    model_name = (
        os.getenv("DEEPSEEK_MODEL", "deepseek-chat")
        if _selected_provider() == "deepseek"
        else os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
    )
    AgentRunRepository.start(stats.run_id, context, model_name)
    run_status = "completed"
    run_error = ""

    try:
        result = agent.invoke(
            {"messages": [{"role": "user", "content": message}]},
            config={"callbacks": [usage], "tags": ["job-tracker-run"]},
        )

        # Extract final message
        messages = result.get("messages", [])
        if messages:
            final = messages[-1]
            content = final.content if hasattr(final, "content") else str(final)
            if isinstance(content, list):
                content = " ".join(
                    part.get("text", "") if isinstance(part, dict) else str(part)
                    for part in content
                )
            print(f"\n{'=' * 60}")
            print("📊 AGENT SUMMARY")
            print("=" * 60)
            print(content)
        else:
            print("\n✅ Agent finished.")

    except Exception as e:
        run_status = "error"
        run_error = str(e)
        logger.exception("Agent error")
        print(f"\n❌ Agent error: {e}")
        sys.exit(1)
    finally:
        elapsed = int(time.monotonic() - budget.start_time)
        stats.apply_runtime_metrics(budget, usage)
        AgentRunRepository.finish(
            stats.run_id, budget, usage.summary(), run_status, run_error,
        )
        stats.print_summary()
        print(f"\n📈 Budget remaining: {budget.max_tool_calls - budget.tool_calls} calls, "
              f"{budget.max_searches - budget.searches} searches, "
              f"{budget.max_notifications - budget.notifications} notifications, "
              f"{elapsed}s elapsed")
