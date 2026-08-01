"""
LangChain-compatible tools for the Company Tracking application.

Each function is decorated with @tool so it can be used by a LangChain
agent, but every function is also a plain callable usable in deterministic
pipelines.
"""

import json
import logging
import os
import re
import time

import requests
from bs4 import BeautifulSoup
from langchain_core.tools import tool

from utils import load_config as _load_config_util
from utils import load_seen_jobs, save_seen_jobs, MIN_JOB_ID_LENGTH

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Retry helper
# ---------------------------------------------------------------------------

RETRY_MAX = 3
RETRY_BACKOFF = 2.0  # seconds, exponential


def _retry_get(url: str, timeout: int = 15) -> requests.Response:
    """GET with exponential backoff retry (3 attempts)."""
    last_exc = None
    for attempt in range(1, RETRY_MAX + 1):
        try:
            resp = requests.get(
                url,
                headers={"User-Agent": "Mozilla/5.0 (compatible; JobTracker/1.0)"},
                timeout=timeout,
            )
            resp.raise_for_status()
            return resp
        except requests.RequestException as exc:
            last_exc = exc
            if attempt < RETRY_MAX:
                wait = RETRY_BACKOFF ** attempt
                logger.debug("Request failed (attempt %d/%d), retrying in %.1fs: %s", attempt, RETRY_MAX, wait, exc)
                time.sleep(wait)
    raise last_exc  # type: ignore[misc]


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

    # --- Fetch page (with retry) ---
    try:
        resp = _retry_get(url)
    except requests.RequestException as e:
        logger.warning("Scrape failed after %d attempts: %s", RETRY_MAX, e)
        return json.dumps({"error": str(e), "jobs": []})

    soup = BeautifulSoup(resp.text, "html.parser")

    # --- Diagnostic: log what LinkedIn returned ---
    page_title = soup.title.get_text(strip=True) if soup.title else "no title"
    html_len = len(resp.text)
    logger.info("LinkedIn response: status=%d, title=%r, html_len=%d", resp.status_code, page_title, html_len)

    # Check for common block signals
    if "login" in page_title.lower() or "sign in" in page_title.lower():
        logger.warning("LinkedIn returned a login page — request was blocked/redirected")
    if html_len < 5000:
        logger.warning("Short response (%d bytes) — likely blocked or empty page", html_len)

    jobs: list[dict] = []

    # --- Strategy 1: Extract from all /jobs/view/ links on the page ---
    # LinkedIn job links always follow the pattern /jobs/view/{jobId}/
    seen_ids: set[str] = set()
    for link in soup.find_all("a", href=re.compile(r"/jobs/view/\d+")):
        href = link.get("href", "")
        job_id_match = re.search(r"/jobs/view/(\d+)", href)
        if not job_id_match:
            continue
        job_id = job_id_match.group(1)
        if len(job_id) < MIN_JOB_ID_LENGTH or job_id in seen_ids:
            continue

        # Try to find the title — it's typically near the link
        title = link.get_text(strip=True)
        if not title or len(title) < 3:
            # Look for title in parent/sibling elements
            parent = link.find_parent(["div", "li", "article"])
            if parent:
                title_el = parent.find(["h3", "h2", "span"], class_=lambda c: c and "title" in c.lower() if c else False)
                if not title_el:
                    title_el = parent.find(["h3", "h2"])
                if title_el:
                    title = title_el.get_text(strip=True)

        if not title or len(title) < 3:
            continue

        # Try to find the company name
        company = ""
        parent = link.find_parent(["div", "li", "article"])
        if parent:
            company_el = parent.find(["h4", "span"], class_=lambda c: c and ("company" in c.lower() or "subtitle" in c.lower()) if c else False)
            if not company_el:
                # Look for text that looks like a company name near the link
                for text_el in parent.find_all(["span", "p", "h4"]):
                    txt = text_el.get_text(strip=True)
                    if txt and txt != title and len(txt) > 2 and not txt.startswith("http"):
                        company = txt
                        break

        # Company filter
        if target_companies and company and not any(
            tc.lower() in company.lower() for tc in target_companies
        ):
            continue

        seen_ids.add(job_id)
        jobs.append({
            "id": job_id,
            "title": title,
            "company": company,
            "url": f"https://www.linkedin.com/jobs/view/{job_id}",
        })

    # --- Strategy 2: Fallback to known CSS selectors ---
    if not jobs:
        logger.info("Strategy 1 found 0 jobs, trying CSS selectors...")
        job_cards = soup.find_all("div", class_=re.compile(r"job.*card|base.*card|job.*result", re.I))
        if not job_cards:
            job_cards = soup.find_all("li", class_=re.compile(r"job|result", re.I))

        for card in job_cards:
            link_el = card.find("a", href=re.compile(r"/jobs/view/\d+"))
            if not link_el:
                continue
            href = link_el.get("href", "")
            job_id_match = re.search(r"/jobs/view/(\d+)", href)
            if not job_id_match:
                continue
            job_id = job_id_match.group(1)
            if len(job_id) < MIN_JOB_ID_LENGTH or job_id in seen_ids:
                continue

            title_el = card.find(["h3", "h2", "strong"])
            title = title_el.get_text(strip=True) if title_el else link_el.get_text(strip=True)
            if not title or len(title) < 3:
                continue

            company = ""
            company_el = card.find(["h4", "span"], class_=re.compile(r"company|subtitle", re.I))
            if company_el:
                company = company_el.get_text(strip=True)

            if target_companies and company and not any(
                tc.lower() in company.lower() for tc in target_companies
            ):
                continue

            seen_ids.add(job_id)
            jobs.append({
                "id": job_id,
                "title": title,
                "company": company,
                "url": f"https://www.linkedin.com/jobs/view/{job_id}",
            })

    if not jobs:
        logger.warning("No job cards found with any strategy.")
        return json.dumps({
            "error": f"No job cards found — page title: '{page_title}', {html_len} bytes.",
            "jobs": [],
        })

    logger.info("Extracted %d jobs from page", len(jobs))
    return json.dumps({"jobs": jobs})


# ---------------------------------------------------------------------------
# 4.  Fetch full job description
# ---------------------------------------------------------------------------

@tool
def get_job_description(job_url: str) -> str:
    """Fetch the full job description from a LinkedIn job posting URL."""
    try:
        resp = _retry_get(job_url)
        soup = BeautifulSoup(resp.text, "html.parser")

        # Primary container
        desc_container = soup.find("div", class_="show-more-less-html__markup")
        if desc_container:
            text = desc_container.get_text(separator="\n", strip=True)
            return text[:4000]

        # Fallback — try the jobs-description container
        desc_el = soup.find("div", class_="jobs-description__content")
        if desc_el:
            return desc_el.get_text(separator="\n", strip=True)[:4000]

        # Second fallback — article container
        article_el = soup.find("article", class_="jobs-description__container")
        if article_el:
            return article_el.get_text(separator="\n", strip=True)[:4000]

        return "ERROR: Could not find job description — page layout may have changed."

    except requests.RequestException as e:
        logger.warning("Description fetch failed after %d attempts: %s", RETRY_MAX, e)
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

        # Reject if the role's max is well below user's experience level
        if required_max < my_experience - 2:
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
