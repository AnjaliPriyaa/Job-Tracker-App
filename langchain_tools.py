"""
LangChain-compatible tools for the Company Tracking application.

Each function is decorated with @tool so it can be used by a LangChain
agent, but every function is also a plain callable usable in deterministic
pipelines.
"""

import json
import os
import re

import requests
from bs4 import BeautifulSoup
from langchain_core.tools import tool

from utils import load_config as _load_config_util
from utils import load_seen_jobs, save_seen_jobs, MIN_JOB_ID_LENGTH

# ---------------------------------------------------------------------------
# 1.  Load configuration
# ---------------------------------------------------------------------------

@tool
def load_config(_: str = "") -> str:
    """Load the job-search configuration from config.json."""
    cfg = _load_config_util()
    return json.dumps(cfg)


# ---------------------------------------------------------------------------
# 2.  Manage seen jobs
# ---------------------------------------------------------------------------

@tool
def manage_seen_jobs(input_data: str) -> str:
    """
    Check or add a job in the seen-jobs set.

    Input JSON:
        {"action": "check", "job_id": "<id>"}
        {"action": "add",   "job_id": "<id>"}
    """
    try:
        data = json.loads(input_data)
    except json.JSONDecodeError:
        return json.dumps({"error": "Invalid JSON input"})

    job_id = str(data.get("job_id", ""))
    if len(job_id) < MIN_JOB_ID_LENGTH:
        return json.dumps({"error": f"job_id too short (min {MIN_JOB_ID_LENGTH} digits)"})

    if data.get("action") == "check":
        seen = job_id in load_seen_jobs()
        return json.dumps({"seen": seen})

    if data.get("action") == "add":
        seen = load_seen_jobs()
        seen.add(job_id)
        save_seen_jobs(seen)
        return json.dumps({"status": "added"})

    return json.dumps({"error": f"Unknown action: {data.get('action')}"})


# ---------------------------------------------------------------------------
# 3.  Scrape jobs from LinkedIn
# ---------------------------------------------------------------------------

@tool
def scrape_jobs(input_data: str) -> str:
    """
    Scrape job cards from a LinkedIn search results page.

    Input JSON:
        {"url": "<linkedin_search_url>", "target_companies": ["Adobe", ...]}
    """
    try:
        data = json.loads(input_data)
    except json.JSONDecodeError:
        return json.dumps({"error": "Invalid JSON input", "jobs": []})

    url = data.get("url", "")
    target_companies = data.get("target_companies", [])

    # --- Fetch page ---
    try:
        resp = requests.get(
            url,
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=15,
        )
        resp.raise_for_status()
    except requests.RequestException as e:
        return json.dumps({"error": str(e), "jobs": []})

    soup = BeautifulSoup(resp.text, "html.parser")

    # --- Find job cards ---
    job_cards = soup.find_all("div", class_=["job-search-card", "base-card"])
    if not job_cards:
        return json.dumps({
            "error": "No job cards found — LinkedIn may have blocked the request or changed its layout.",
            "jobs": [],
        })

    jobs: list[dict] = []

    for card in job_cards:
        # Primary selectors
        title_el = card.find("h3", class_="base-search-card__title")
        company_el = card.find("h4", class_="base-search-card__subtitle")
        link_el = card.find("a", class_="base-card__full-link")

        # Fallbacks
        if not link_el:
            link_el = card.find("a")
        if not title_el:
            title_el = card.find("h3")
        if not company_el:
            company_el = card.find("h4")

        if not (title_el and company_el and link_el):
            continue

        title = title_el.get_text(strip=True)
        company = company_el.get_text(strip=True)
        link_href = link_el.get("href", "")

        # Company filter (only when target list is non-empty)
        if target_companies and not any(
            tc.lower() in company.lower() for tc in target_companies
        ):
            continue

        # Extract job ID
        job_id_match = re.search(r"currentJobId=(\d+)", link_href) or re.search(
            r"-(\d+)", link_href
        )
        if not job_id_match:
            continue

        job_id = job_id_match.group(1)
        if len(job_id) < MIN_JOB_ID_LENGTH:
            continue  # skip bogus IDs

        jobs.append({
            "id": job_id,
            "title": title,
            "company": company,
            "url": f"https://www.linkedin.com/jobs/view/{job_id}",
        })

    return json.dumps({"jobs": jobs})


# ---------------------------------------------------------------------------
# 4.  Fetch full job description
# ---------------------------------------------------------------------------

@tool
def get_job_description(job_url: str) -> str:
    """Fetch the full job description from a LinkedIn job posting URL."""
    try:
        resp = requests.get(
            job_url,
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=15,
        )
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        # Primary container
        desc_container = soup.find("div", class_="jobs-description")
        if desc_container:
            text = desc_container.get_text(separator="\n", strip=True)
            return text[:4000]

        # Fallback
        desc_el = soup.find("div", class_="show-more-less-html__markup")
        if desc_el:
            return desc_el.get_text(separator="\n", strip=True)[:4000]

        return "ERROR: Could not find job description — page layout may have changed."

    except requests.RequestException as e:
        return f"ERROR: {e}"


# ---------------------------------------------------------------------------
# 5.  Send Telegram notification
# ---------------------------------------------------------------------------

@tool
def send_telegram(message: str) -> str:
    """Send a Telegram message to the configured chat."""
    from utils import send_telegram as _send

    token = os.getenv("TELEGRAM_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")

    if not token or not chat_id:
        return "Telegram not configured"

    ok = _send(message)
    return "sent" if ok else "failed"


# ---------------------------------------------------------------------------
# 6.  Filter jobs by experience level
# ---------------------------------------------------------------------------

@tool
def filter_jobs_by_experience(input_data: str) -> str:
    """
    Filter jobs based on required years of experience.

    Input JSON:
        {"jobs": [{"title": "...", "description": "..."}, ...],
         "my_experience": 6.0,
         "max_experience": 6}
    """
    try:
        data = json.loads(input_data)
    except json.JSONDecodeError:
        return json.dumps({"error": "Invalid JSON input", "filtered_jobs": []})

    my_experience = float(data.get("my_experience", 5))
    max_experience = float(data.get("max_experience", my_experience))
    jobs = data.get("jobs", [])

    filtered: list[dict] = []

    for job in jobs:
        title = job.get("title", "").lower()
        desc = job.get("description", "").lower()

        # Junior / entry-level → always include
        if any(kw in title for kw in ["junior", "entry-level", "graduate", "associate"]):
            filtered.append(job)
            continue

        # Extract experience requirements from description
        exp_range = re.search(r"(\d+)\s*[-–]\s*(\d+)\s*years?", desc)
        exp_plus = re.search(r"(\d+)\+\s*years?", desc)
        exp_min = re.search(r"(?:minimum|at least|min\.?)\s*(?:of\s+)?(\d+)\s*years?", desc)
        exp_single = re.search(r"(\d+)\s*years?", desc)

        required_min = 0
        required_max = float("inf")

        if exp_range:
            required_min = int(exp_range.group(1))
            required_max = int(exp_range.group(2))
        elif exp_plus:
            required_min = int(exp_plus.group(1))
        elif exp_min:
            required_min = int(exp_min.group(1))
        elif exp_single:
            required_min = int(exp_single.group(1))
            required_max = required_min + 2

        # Reject if the role requires more than the user's max
        if required_min > max_experience + 1.5:
            continue

        # User's experience fits within the required range (with 1.5 yr flexibility)
        if required_min <= my_experience + 1.5:
            filtered.append(job)

    return json.dumps({"filtered_jobs": filtered})


# ---------------------------------------------------------------------------
# Tool registry
# ---------------------------------------------------------------------------

ALL_TOOLS = [
    load_config,
    scrape_jobs,
    get_job_description,
    manage_seen_jobs,
    send_telegram,
    filter_jobs_by_experience,
]
