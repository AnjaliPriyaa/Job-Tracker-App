"""
Agentic Multi-Source Job Tracker using DeepAgents harness.

Uses create_deep_agent() to orchestrate job searches across LinkedIn,
Naukri, Indeed, Instahyre, and company career pages — with AI matching
via DeepSeek and Telegram notifications.

Run:
    python agentic_tracker.py
"""

import json
import logging
import os
import sys

from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("agentic_tracker")

# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------

from langchain_core.tools import tool

from langchain_tools import (
    get_job_description,
    load_config,
    manage_seen_jobs,
    send_telegram,
)

from tools.scraper_tools import (
    search_linkedin,
    search_career_pages,
)

from langchain_ai import match_job_tool


# Wrap match_job_tool as a LangChain @tool for the agent
@tool
def match_job(job_data: str) -> str:
    """
    Evaluate a job against user preferences using AI (DeepSeek).

    Input JSON must include: title, company, description, keywords,
    target_companies, target_roles, exclude_keywords, exclude_roles,
    exclude_levels, max_experience, min_experience.

    Returns: {"match": true/false, "confidence": 0.0-1.0, "reason": "..."}
    """
    return match_job_tool(job_data)


# ---- All tools the agent can use ----
AGENT_TOOLS = [
    load_config,
    search_linkedin,
    search_career_pages,
    get_job_description,
    match_job,
    send_telegram,
    manage_seen_jobs,
]

# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """You are an autonomous job search agent. Your mission: find
DevOps/Cloud/SRE jobs across LinkedIn and company career pages (Greenhouse, Lever, Ashby),
evaluate them against the user's strict criteria, and notify them via Telegram.

## WORKFLOW

1. **Load config**: Call `load_config` to get the user's preferences.
   It contains: target_companies, target_roles, keywords, exclusions, experience range, and portal URLs.

2. **Search both sources**:
   - `search_linkedin`: Pass {"url": linkedin_url, "target_companies": [...]}
   - `search_career_pages`: Pass {"target_companies": [...]}
   Each returns: {"jobs": [{"id":..., "title":..., "company":..., "url":..., "source":...}]}

3. **For each job found**:
   a. Call `get_job_description` with the job URL to get full description, company name, and title
      Returns: {"description": "...", "company": "ActualCompany", "title": "ActualTitle"}
   b. Check company: if the actual company is NOT in target_companies → skip (do NOT call match_job, just mark seen)
   c. Call `manage_seen_jobs` with action="check" to see if already processed
   d. Call `match_job` with ALL criteria
   e. If match=true AND confidence >= 0.6:
      - Call `send_telegram` with: "🔔 *Title*\n🏢 Company\n🔗 URL\n_reason_"
      - Call `manage_seen_jobs` action="add"
   f. If match=false: call manage_seen_jobs action="add" (don't re-evaluate)

4. **Report summary**: Total jobs found, matched, and notified from each source.

## MATCHING RULES (enforced by match_job)

- Company MUST be in target_companies list
- Role MUST align with target_roles (DevOps/Cloud/SRE/Platform)
- Must NOT be C/C++ networking, frontend, or unrelated roles
- Must contain at least one keyword
- Must NOT contain excluded keywords/roles/levels
- Experience must be within range

## IMPORTANT

- Process jobs efficiently — skip obvious non-matches
- Always check company against target list BEFORE calling match_job
- Keep Telegram messages concise (reason max 150 chars)
- Always mark jobs as seen after processing
"""

# ---------------------------------------------------------------------------
# Build the DeepAgent
# ---------------------------------------------------------------------------


def _build_agent():
    """Create the DeepAgent with all tools and middleware."""
    from langchain_openai import ChatOpenAI

    deepseek_key = os.getenv("DEEPSEEK_API_KEY")
    gemini_key = os.getenv("GEMINI_API_KEY")

    if deepseek_key:
        model_name = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")
        llm = ChatOpenAI(
            model=model_name,
            temperature=0.1,
            openai_api_key=deepseek_key,
            openai_api_base="https://api.deepseek.com",
        )
        logger.info("Using DeepSeek: %s", model_name)
    elif gemini_key:
        from langchain_google_genai import ChatGoogleGenerativeAI

        model_name = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
        llm = ChatGoogleGenerativeAI(
            model=model_name,
            temperature=0.1,
            google_api_key=gemini_key,
        )
        logger.info("Using Gemini: %s", model_name)
    else:
        print("❌ Set DEEPSEEK_API_KEY or GEMINI_API_KEY in .env")
        sys.exit(1)

    try:
        from deepagents import create_deep_agent
    except ImportError:
        print("❌ deepagents package not installed. Requires Python 3.11+.")
        print("   Install: pip install deepagents")
        print("   Or use the deterministic pipeline: python agent_app_simple.py")
        sys.exit(1)

    from langchain.agents.middleware import TodoListMiddleware

    agent = create_deep_agent(
        model=llm,
        tools=AGENT_TOOLS,
        system_prompt=SYSTEM_PROMPT,
        middleware=[
            TodoListMiddleware(),
        ],
    )

    return agent


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("🤖 Starting Agentic Multi-Source Job Tracker...")
    print(f"   Sources: LinkedIn + Company Career Pages")
    print(f"   Model: DeepSeek (deepseek-chat)")
    print()

    try:
        agent = _build_agent()

        result = agent.invoke({
            "messages": [{
                "role": "user",
                "content": (
                    "Find jobs across all platforms (LinkedIn, Naukri, Indeed, Instahyre, "
                    "and company career pages) that match the user's criteria. "
                    "Start by loading the config, then search all platforms, evaluate each job, "
                    "and send Telegram notifications for matches. Be thorough but efficient."
                ),
            }]
        })

        messages = result.get("messages", [])
        if messages:
            final = messages[-1]
            content = final.content if hasattr(final, "content") else str(final)
            if isinstance(content, list):
                content = " ".join(
                    part.get("text", "") if isinstance(part, dict) else str(part)
                    for part in content
                )
            print(f"\n✅ Agent finished:\n{content}")
        else:
            print("\n✅ Agent finished.")

    except Exception as e:
        logger.exception("Agent error")
        print(f"\n❌ Agent error: {e}")
        sys.exit(1)
