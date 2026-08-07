"""
Platform-specific job scraping tools.

Each @tool function searches a different job platform and returns
standardized job listings: {"jobs": [{"id":..., "title":..., "company":..., "url":..., "source":...}]}

The agent calls these tools in parallel via subagents.
"""

import json
import logging
import re
import time

import requests
from bs4 import BeautifulSoup
from langchain_core.tools import tool

logger = logging.getLogger(__name__)

RETRY_MAX = 3
RETRY_BACKOFF = 2.0


def _retry_get(url: str, timeout: int = 15, extra_headers=None) -> requests.Response:
    """GET with exponential backoff retry."""
    headers = {"User-Agent": "Mozilla/5.0 (compatible; JobTracker/1.0)"}
    if extra_headers:
        headers.update(extra_headers)

    last_exc = None
    for attempt in range(1, RETRY_MAX + 1):
        try:
            resp = requests.get(url, headers=headers, timeout=timeout)
            resp.raise_for_status()
            return resp
        except requests.RequestException as exc:
            last_exc = exc
            if attempt < RETRY_MAX:
                wait = RETRY_BACKOFF**attempt
                time.sleep(wait)
    raise last_exc


# ===========================================================================
# LinkedIn
# ===========================================================================

@tool
def search_linkedin(input_data: str) -> str:
    """
    Search LinkedIn for jobs matching criteria.

    Input JSON: {"url": "<linkedin_search_url>", "target_companies": [...]}
    Returns JSON: {"jobs": [{"id":..., "title":..., "company":..., "url":..., "source":"linkedin"}]}
    """
    try:
        data = json.loads(input_data)
    except json.JSONDecodeError:
        return json.dumps({"error": "Invalid JSON", "jobs": []})

    url = data.get("url", "")
    target_companies = data.get("target_companies", [])

    try:
        resp = _retry_get(url)
    except requests.RequestException as e:
        return json.dumps({"error": str(e), "jobs": []})

    raw_html = resp.text
    jobs: list[dict] = []
    seen_ids: set[str] = set()

    # Extract job URNs from embedded data
    for match in re.finditer(r"urn:li:jobPosting:(\d{7,15})", raw_html):
        job_id = match.group(1)
        if job_id not in seen_ids:
            seen_ids.add(job_id)
            jobs.append({
                "id": f"li_{job_id}",
                "title": "",
                "company": "",
                "url": f"https://www.linkedin.com/jobs/view/{job_id}",
                "source": "linkedin",
            })

    logger.info("LinkedIn: found %d jobs", len(jobs))
    return json.dumps({"jobs": jobs})


# ===========================================================================
# Company Career Pages (Greenhouse, Lever, Ashby)
# ===========================================================================

def _company_to_slug(company: str) -> str:
    """Convert company name to likely ATS slug."""
    return company.lower().replace(" ", "").replace(".", "").replace("&", "")


@tool
def search_career_pages(input_data: str) -> str:
    """
    Search company career pages (Greenhouse, Lever, Ashby) for jobs.

    Input JSON: {"target_companies": ["Adobe", "Stripe", ...]}
    Returns JSON: {"jobs": [{"id":..., "title":..., "company":..., "url":..., "source":"career_page"}]}
    """
    try:
        data = json.loads(input_data)
    except json.JSONDecodeError:
        return json.dumps({"error": "Invalid JSON", "jobs": []})

    target_companies = data.get("target_companies", [])
    companies_to_check = target_companies[:50]

    all_jobs: list[dict] = []
    seen_ids: set[str] = set()
    found_companies: list[str] = []
    skipped_companies: list[str] = []

    # Known ATS URL patterns
    ats_patterns = [
        "https://boards.greenhouse.io/{slug}",
        "https://jobs.lever.co/{slug}",
        "https://jobs.ashbyhq.com/{slug}",
    ]

    logger.info("Checking career pages for %d companies...", len(companies_to_check))

    for company in companies_to_check:
        slug = _company_to_slug(company)
        found = False

        for pattern in ats_patterns:
            url = pattern.format(slug=slug)
            try:
                resp = _retry_get(url, timeout=10)
            except requests.RequestException:
                continue

            soup = BeautifulSoup(resp.text, "html.parser")
            page_jobs = 0

            for link in soup.find_all("a", href=True):
                href = link.get("href", "")
                title = link.get_text(strip=True)

                if not title or len(title) < 5:
                    continue
                if any(skip in title.lower() for skip in ["department", "location", "team", "view all"]):
                    continue

                if href.startswith("/"):
                    base = "/".join(url.split("/")[:3])
                    href = base + href

                job_id = str(hash(href))
                if job_id in seen_ids:
                    continue
                seen_ids.add(job_id)

                all_jobs.append({
                    "id": f"cp_{job_id}",
                    "title": title,
                    "company": company,
                    "url": href,
                    "source": "career_page",
                })
                page_jobs += 1

            if page_jobs > 0:
                logger.info("  ✅ %s → %d jobs (%s)", company, page_jobs, url)
                found_companies.append(company)
                found = True
                break

        if not found:
            skipped_companies.append(company)

    logger.info("Career pages: %d jobs from %d companies", len(all_jobs), len(found_companies))
    if found_companies:
        logger.info("  Companies with jobs: %s", ", ".join(found_companies))
    if skipped_companies:
        logger.debug("  No career page found for: %s", ", ".join(skipped_companies[:10]))

    return json.dumps({"jobs": all_jobs})


# ===========================================================================
# Tool registry
# ===========================================================================

ALL_SCRAPER_TOOLS = [
    search_linkedin,
    search_career_pages,
]
