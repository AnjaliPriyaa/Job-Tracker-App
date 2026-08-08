"""Search tools with typed Pydantic schemas."""

import json
import logging
import re
import time

import requests
from langchain_core.tools import tool
from pydantic import BaseModel, Field

from models.search import SearchResult

logger = logging.getLogger(__name__)

RETRY_MAX = 2
RETRY_BACKOFF = 2.0


def _retry_get(url: str, timeout: int = 15, extra_headers: dict | None = None) -> requests.Response:
    from tools.url_security import validate_url
    safe, reason = validate_url(url)
    if not safe:
        raise ValueError(f"URL validation failed: {reason}")
    headers = {"User-Agent": "Mozilla/5.0 (compatible; JobTracker/1.0)"}
    if extra_headers:
        headers.update(extra_headers)
    last_exc = None
    for attempt in range(RETRY_MAX + 1):
        try:
            resp = requests.get(url, headers=headers, timeout=timeout)
            resp.raise_for_status()
            return resp
        except requests.RequestException as exc:
            last_exc = exc
            if attempt < RETRY_MAX:
                time.sleep(RETRY_BACKOFF ** attempt)
    raise last_exc


# ===========================================================================
# LinkedIn
# ===========================================================================

class LinkedInSearchInput(BaseModel):
    url: str = Field(description="LinkedIn search URL")
    max_results: int = Field(default=30, ge=1, le=100)


@tool(args_schema=LinkedInSearchInput)
def search_linkedin(url: str, max_results: int = 30) -> str:
    """
    Search LinkedIn for jobs. Provide a LinkedIn search URL. Returns structured job results.
    Use this for broad searches like "DevOps engineer in Bengaluru".
    """
    try:
        resp = _retry_get(url)
    except requests.RequestException as e:
        return json.dumps({"results": [], "error": f"LinkedIn request failed: {e}"})

    raw_html = resp.text
    results: list[dict] = []
    seen: set[str] = set()

    for match in re.finditer(r"urn:li:jobPosting:(\d{7,15})", raw_html):
        job_id = match.group(1)
        if job_id not in seen and len(results) < max_results:
            seen.add(job_id)
            results.append(SearchResult(
                source="linkedin",
                source_job_id=job_id,
                url=f"https://www.linkedin.com/jobs/view/{job_id}",
                title="",
                company="",
                location="",
            ).model_dump())

    if not results:
        # Fallback: /jobs/view/ links
        for match in re.finditer(r"/jobs/view/(\d{7,15})", raw_html):
            job_id = match.group(1)
            if job_id not in seen and len(results) < max_results:
                seen.add(job_id)
                results.append(SearchResult(
                    source="linkedin",
                    source_job_id=job_id,
                    url=f"https://www.linkedin.com/jobs/view/{job_id}",
                ).model_dump())

    logger.info("LinkedIn search: %d results", len(results))
    return json.dumps({"results": results, "error": None if results else "No job IDs found"})


# ATS search (Greenhouse, Lever, Ashby)
# ===========================================================================

class ATSSearchInput(BaseModel):
    company: str = Field(description="Company name to search for")
    ats_url: str = Field(description="ATS career page URL (e.g., https://boards.greenhouse.io/airbnb)")
    max_results: int = Field(default=25, ge=1, le=100)


@tool(args_schema=ATSSearchInput)
def search_ats(company: str, ats_url: str, max_results: int = 25) -> str:
    """
    Search a company's ATS (Greenhouse, Lever, Ashby) career page for jobs.
    Requires the ATS URL from discover_company_career_page.
    """
    try:
        resp = _retry_get(ats_url, timeout=10)
    except requests.RequestException as e:
        return json.dumps({"results": [], "error": f"ATS request failed: {e}"})

    from bs4 import BeautifulSoup
    soup = BeautifulSoup(resp.text, "html.parser")
    for tag in soup.find_all(["nav", "footer", "header", "script", "style"]):
        tag.decompose()

    results: list[dict] = []
    seen: set[str] = set()

    for link in soup.find_all("a", href=True):
        href = link.get("href", "")
        title = link.get_text(strip=True)
        if not title or len(title) < 8:
            continue
        if href.startswith("/"):
            base = "/".join(ats_url.split("/")[:3])
            href = base + href
        if href in seen:
            continue
        seen.add(href)

        if len(results) < max_results:
            results.append(SearchResult(
                source="ats",
                source_job_id=href,
                url=href,
                title=title,
                company=company,
            ).model_dump())

    logger.info("ATS search (%s): %d results", company, len(results))
    return json.dumps({"results": results, "error": None if results else f"No jobs found at {ats_url}"})
