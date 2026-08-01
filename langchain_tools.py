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
    raw_html = resp.text

    # --- Diagnostic: log what LinkedIn returned ---
    page_title = soup.title.get_text(strip=True) if soup.title else "no title"
    html_len = len(raw_html)
    logger.info("LinkedIn response: status=%d, title=%r, html_len=%d", resp.status_code, page_title, html_len)

    # Check for common block signals
    if "login" in page_title.lower() or "sign in" in page_title.lower():
        logger.warning("LinkedIn returned a login page — request was blocked/redirected")
    if html_len < 5000:
        logger.warning("Short response (%d bytes) — likely blocked or empty page", html_len)

    jobs: list[dict] = []
    seen_ids: set[str] = set()

    # --- Strategy 1: Extract job URNs from embedded JSON/JS ---
    # LinkedIn embeds job data as urn:li:jobPosting:ID in scripts and attributes
    for match in re.finditer(r'urn:li:jobPosting:(\d{7,15})', raw_html):
        job_id = match.group(1)
        if job_id not in seen_ids:
            seen_ids.add(job_id)
            jobs.append({
                "id": job_id,
                "title": "",
                "company": "",
                "url": f"https://www.linkedin.com/jobs/view/{job_id}",
            })

    if jobs:
        logger.info("Strategy 1 (URNs): found %d jobs", len(jobs))
    else:
        # --- Strategy 2: Find /jobs/view/ links in script/data tags ---
        # Sometimes the links are in JSON strings inside scripts
        for match in re.finditer(r'/jobs/view/(\d{7,15})', raw_html):
            job_id = match.group(1)
            if job_id not in seen_ids:
                seen_ids.add(job_id)
                jobs.append({
                    "id": job_id,
                    "title": "",
                    "company": "",
                    "url": f"https://www.linkedin.com/jobs/view/{job_id}",
                })

        if jobs:
            logger.info("Strategy 2 (view links in HTML): found %d jobs", len(jobs))
        else:
            # --- Strategy 3: Try data attributes ---
            for match in re.finditer(r'data-job-id=["\']?(\d{7,15})', raw_html):
                job_id = match.group(1)
                if job_id not in seen_ids:
                    seen_ids.add(job_id)
                    jobs.append({
                        "id": job_id,
                        "title": "",
                        "company": "",
                        "url": f"https://www.linkedin.com/jobs/view/{job_id}",
                    })

            if jobs:
                logger.info("Strategy 3 (data-job-id): found %d jobs", len(jobs))
            else:
                # --- Strategy 4: Try entityUrn patterns ---
                for match in re.finditer(r'"entityUrn"\s*:\s*"urn:li:jobPosting:(\d{7,15})"', raw_html):
                    job_id = match.group(1)
                    if job_id not in seen_ids:
                        seen_ids.add(job_id)
                        jobs.append({
                            "id": job_id,
                            "title": "",
                            "company": "",
                            "url": f"https://www.linkedin.com/jobs/view/{job_id}",
                        })

                if jobs:
                    logger.info("Strategy 4 (entityUrn): found %d jobs", len(jobs))
                else:
                    # --- Strategy 5: Broad pattern — any 10-digit number near 'job' ---
                    for match in re.finditer(r'job[/"\'][^}]*?(\d{10})', raw_html, re.I):
                        job_id = match.group(1)
                        if job_id not in seen_ids and len(job_id) >= 10:
                            seen_ids.add(job_id)
                            jobs.append({
                                "id": job_id,
                                "title": "",
                                "company": "",
                                "url": f"https://www.linkedin.com/jobs/view/{job_id}",
                            })

    # --- Try to enrich jobs with title/company from the page ---
    if jobs:
        # Look for job titles and companies near each job ID in the raw HTML
        for job in jobs:
            jid = job["id"]
            # Try to find title near the job ID
            title_match = re.search(
                rf'{jid}.*?"title"\s*:\s*"([^"]+)"',
                raw_html
            )
            if not title_match:
                # Try JSON-LD or other structured formats
                title_match = re.search(
                    rf'jobPosting.*?{jid}.*?"title"\s*:\s*"([^"]+)"',
                    raw_html, re.DOTALL
                )
            if title_match:
                job["title"] = title_match.group(1)

            # Try to find company
            company_match = re.search(
                rf'{jid}.*?"companyName"\s*:\s*"([^"]+)"',
                raw_html
            )
            if not company_match:
                company_match = re.search(
                    rf'{jid}.*?"name"\s*:\s*"([^"]+)"',
                    raw_html
                )
            if company_match:
                job["company"] = company_match.group(1)

        # Company filter
        if target_companies:
            filtered = []
            for job in jobs:
                company = job.get("company", "")
                if company and not any(tc.lower() in company.lower() for tc in target_companies):
                    continue
                filtered.append(job)
            jobs = filtered

        logger.info("Extracted %d jobs from page (IDs from embedded data)", len(jobs))
        return json.dumps({"jobs": jobs})

    # --- Last resort: save page snippet and report failure ---
    snippet = raw_html[:800]
    logger.warning("All strategies failed. Page snippet: %s", snippet)
    return json.dumps({
        "error": f"No job data found — page title: '{page_title}', {html_len} bytes.",
        "jobs": [],
    })


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
