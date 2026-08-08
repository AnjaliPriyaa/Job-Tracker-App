#!/usr/bin/env python3
"""
Agentic Multi-Source Job Tracker.

Single entry point. Uses DeepAgents harness with typed tools,
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

# ---------------------------------------------------------------------------
# Build the agent
# ---------------------------------------------------------------------------


def build_agent():
    """Create the agentic job search agent."""
    from langchain_openai import ChatOpenAI
    from deepagents import create_deep_agent
    from langchain.agents.middleware import TodoListMiddleware

    from tools import ALL_TOOLS
    from agent.prompts import SYSTEM_PROMPT
    from agent.middleware import BudgetMiddleware, BudgetTracker

    # Model
    deepseek_key = os.getenv("DEEPSEEK_API_KEY")
    gemini_key = os.getenv("GEMINI_API_KEY")

    if deepseek_key:
        model = ChatOpenAI(
            model=os.getenv("DEEPSEEK_MODEL", "deepseek-chat"),
            temperature=0.1,
            openai_api_key=deepseek_key,
            openai_api_base="https://api.deepseek.com",
        )
        logger.info("Model: DeepSeek (%s)", os.getenv("DEEPSEEK_MODEL", "deepseek-chat"))
    elif gemini_key:
        from langchain_google_genai import ChatGoogleGenerativeAI
        model = ChatGoogleGenerativeAI(
            model=os.getenv("GEMINI_MODEL", "gemini-2.5-flash"),
            temperature=0.1,
            google_api_key=gemini_key,
        )
        logger.info("Model: Gemini (%s)", os.getenv("GEMINI_MODEL", "gemini-2.5-flash"))
    else:
        print("❌ Set DEEPSEEK_API_KEY or GEMINI_API_KEY in .env")
        sys.exit(1)

    # Emergency budget (runaway protection only, not search limits)
    budget = BudgetTracker(max_tool_calls=500, timeout_seconds=720)

    agent = create_deep_agent(
        model=model,
        tools=ALL_TOOLS,
        system_prompt=SYSTEM_PROMPT,
        middleware=[
            TodoListMiddleware(),
            BudgetMiddleware(budget),
        ],
    )

    logger.info("Agent built: %d tools, emergency budget=%d calls/%ds",
                len(ALL_TOOLS), budget.max_tool_calls, budget.timeout_seconds)

    return agent, budget


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    context = os.getenv("RUN_CONTEXT", "full")

    CONTEXT_MESSAGES = {
        "linkedin": (
            "Search LinkedIn for DevOps, Cloud, SRE, and Platform Engineering jobs "
            "matching the user's preferences. Start by getting preferences, then use "
            "search_linkedin with the LinkedIn URL from preferences. For each promising "
            "job, fetch details, evaluate, and notify. If you find interesting companies, "
            "you may also use discover_company_career_page and search_ats to dig deeper. "
            "Focus on quality over quantity. Adapt based on what you find."
        ),
        "career": (
            "Discover and search company career pages for DevOps, Cloud, SRE, and Platform "
            "Engineering jobs. Start by getting preferences to see which companies to target. "
            "Use discover_company_career_page for each target company, then search_ats for "
            "those you find. You may also use search_linkedin as a supplement. For each job, "
            "fetch details, evaluate, and notify strong matches. Investigate uncertain jobs. "
            "Stop when you've covered enough companies or found sufficient matches."
        ),
        "full": (
            "Find DevOps, Cloud, SRE, and Platform Engineering jobs matching the "
            "user's preferences. Start by getting preferences, then search broadly "
            "using all available tools. Evaluate promising jobs and notify the user "
            "of strong matches. Be thorough, use multiple sources, and adapt your "
            "strategy based on results."
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

    try:
        result = agent.invoke({
            "messages": [{"role": "user", "content": message}]
        })

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
        logger.exception("Agent error")
        print(f"\n❌ Agent error: {e}")
        sys.exit(1)
    finally:
        elapsed = int(time.monotonic() - budget.start_time)
        print(f"\n📈 Budget: {budget.tool_calls}/{budget.max_tool_calls} calls, "
              f"{budget.searches} searches, {budget.notifications} notifications, "
              f"{elapsed}s elapsed")
