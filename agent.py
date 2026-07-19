"""
LLM Agent-based job tracker (alternative to the deterministic pipeline).

Uses LangGraph's create_react_agent to let Gemini orchestrate tool calls.
The deterministic pipeline in agent_app_simple.py is recommended for most
use cases — this agent is provided for experimentation.

Run directly:
    python agent.py
"""

import json
import os
import sys

from dotenv import load_dotenv

load_dotenv()


def _build_agent():
    """Create the LangGraph ReAct agent (lazy init — only when run directly)."""
    from langchain_google_genai import ChatGoogleGenerativeAI
    from langgraph.prebuilt import create_react_agent
    from langchain_tools import ALL_TOOLS, load_config as _load_config_tool

    llm = ChatGoogleGenerativeAI(
        model="gemini-2.5-flash",
        temperature=0.2,
        google_api_key=os.getenv("GEMINI_API_KEY"),
    )

    # Build system prompt dynamically from config
    try:
        raw = _load_config_tool.invoke({})
        cfg = json.loads(raw)
    except Exception:
        cfg = {}

    exp_max = cfg.get("experience_years", 6)
    exp_min = cfg.get("min_experience_years", 4)
    exclude_roles = ", ".join(cfg.get("exclude_roles", [])[:8])
    target_count = len(cfg.get("target_companies", []))
    role_count = len(cfg.get("roles", []))

    system_prompt = f"""You are an autonomous job search agent.

Your goal: find HIGH QUALITY job matches and notify the user.

STRICT MATCHING RULES:
- Only target companies ({target_count} configured)
- Must match at least one role keyword ({role_count} roles configured)
- Experience: {exp_min}–{exp_max} years
- Reject these roles: {exclude_roles}
- Reject >{exp_max} years experience requirements
- Prefer individual contributor roles

WORKFLOW:
1. Call load_config to get the user's preferences
2. Call scrape_jobs with the LinkedIn URL and target companies
3. For each job returned:
   a. Call manage_seen_jobs to check if already processed
   b. Call get_job_description to fetch full details
   c. Evaluate relevance YOURSELF using the rules above
   d. If it's a strong match → call send_telegram to notify
   e. Call manage_seen_jobs to mark as processed
4. Call filter_jobs_by_experience if you need to narrow by years

IMPORTANT:
- YOU decide match quality — there is no separate matching tool
- Be selective: quality > quantity
- Only notify for genuinely strong matches
"""

    return create_react_agent(model=llm, tools=ALL_TOOLS, prompt=system_prompt)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    if not os.getenv("GEMINI_API_KEY"):
        print("❌ GEMINI_API_KEY not set. Create a .env file or export the variable.")
        sys.exit(1)

    print("🤖 Starting LLM Agent Job Tracker...")

    agent_executor = _build_agent()

    try:
        result = agent_executor.invoke({
            "messages": [{
                "role": "user",
                "content": "Find jobs based on the user's configuration. Start by loading the config."
            }]
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
            print(f"\n✅ Agent finished:\n{content}")
        else:
            print("\n✅ Agent finished (no messages returned).")

    except Exception as e:
        print(f"\n❌ Agent error: {e}")
        sys.exit(1)
