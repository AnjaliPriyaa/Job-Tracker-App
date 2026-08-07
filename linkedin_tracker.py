"""
LinkedIn-only job tracker using DeepAgents.

Searches LinkedIn, fetches descriptions, matches with DeepSeek, notifies via Telegram.
Runs in parallel with career_pages_tracker.py in CI.
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
logger = logging.getLogger("linkedin_tracker")


def main():
    from langchain_openai import ChatOpenAI
    from deepagents import create_deep_agent
    from langchain.agents.middleware import TodoListMiddleware
    from langchain_core.tools import tool

    from tools.scraper_tools import search_linkedin
    from langchain_tools import get_job_description, send_telegram, manage_seen_jobs
    from langchain_ai import match_job_tool
    from utils import load_config

    @tool
    def match_job(job_data: str) -> str:
        """Evaluate a job. Input JSON with title, company, description, keywords, target_companies, target_roles, etc."""
        return match_job_tool(job_data)

    deepseek_key = os.getenv("DEEPSEEK_API_KEY")
    if not deepseek_key:
        print("❌ DEEPSEEK_API_KEY not set")
        sys.exit(1)

    llm = ChatOpenAI(
        model=os.getenv("DEEPSEEK_MODEL", "deepseek-chat"),
        temperature=0.1,
        openai_api_key=deepseek_key,
        openai_api_base="https://api.deepseek.com",
    )

    system_prompt = """You search LinkedIn for DevOps/Cloud/SRE jobs and notify via Telegram.

WORKFLOW:
1. Load config.json (use Python's json module directly — read the file)
2. Call search_linkedin with the LinkedIn URL from config's job_portals
3. For each job:
   a. Call get_job_description → returns {"description":"...","company":"...","title":"..."}
   b. Check: is the company in target_companies? If not → manage_seen_jobs action="add", skip
   c. Call match_job with ALL criteria
   d. If match=true AND confidence >= 0.6 → send_telegram → manage_seen_jobs action="add"
   e. If match=false → manage_seen_jobs action="add"
4. Report total found, matched, notified

Telegram format: "🔔 *Title*\n🏢 Company\n📌 [LinkedIn]\n🔗 URL\n📂 linkedin_search_url\n_reason(max 120 chars)_"
Include 📌 [LinkedIn] tag and 📂 with the LinkedIn search URL in every message.
"""

    agent = create_deep_agent(
        model=llm,
        tools=[search_linkedin, get_job_description, match_job, send_telegram, manage_seen_jobs],
        system_prompt=system_prompt,
        middleware=[TodoListMiddleware()],
    )

    config = load_config()

    result = agent.invoke({
        "messages": [{
            "role": "user",
            "content": (
                f"Search LinkedIn for DevOps/Cloud/SRE jobs. "
                f"The LinkedIn URL is: {config['job_portals'][0]['career_page']}\n"
                f"Target companies: {json.dumps(config['target_companies'])}\n"
                f"Target roles: {json.dumps(config['roles'])}\n"
                f"Keywords: {json.dumps(config['job_portals'][0]['keywords'])}\n"
                f"Exclude keywords: {json.dumps(config['exclude_keywords'])}\n"
                f"Exclude roles: {json.dumps(config['exclude_roles'])}\n"
                f"Exclude levels: {json.dumps(config['exclude_levels'])}\n"
                f"Experience: {config['min_experience_years']}-{config['experience_years']} years\n"
                f"Confidence threshold: {config.get('confidence_threshold', 0.6)}\n\n"
                f"Search and process all jobs. Be thorough."
            ),
        }]
    })

    messages = result.get("messages", [])
    if messages:
        final = messages[-1]
        content = final.content if hasattr(final, "content") else str(final)
        print(f"\n✅ LinkedIn tracker finished:\n{content}")
    else:
        print("\n✅ LinkedIn tracker finished.")


if __name__ == "__main__":
    print("🔍 LinkedIn Job Tracker")
    main()
