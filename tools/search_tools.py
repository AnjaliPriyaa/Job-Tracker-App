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


# ===========================================================================
# Web search (broad fallback / discovery)
# ===========================================================================

class WebSearchInput(BaseModel):
    query: str = Field(description="Search query for jobs, e.g. 'DevOps engineer Bengaluru'")
    location: str = Field(default="India", description="Location filter")
    max_results: int = Field(default=15, ge=1, le=50)


@tool(args_schema=WebSearchInput)
def search_web_jobs(query: str, location: str = "India", max_results: int = 15) -> str:
    """
    Broad web-based job discovery. Searches multiple public job sources
    by constructing direct URLs to aggregators and career platforms.

    Use when platform-specific tools don't find enough results, or when
    discovering jobs from sources not covered by other tools.
    """
    results: list[dict] = []
    seen: set[str] = set()
    q = requests.utils.quote(query)

    # Source 1: Indeed (mobile-friendly endpoint)
    try:
        indeed_url = f"https://in.indeed.com/jobs?q={q}&l={requests.utils.quote(location)}&fromage=7"
        resp = _retry_get(indeed_url, timeout=10, extra_headers={
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "en-US,en;q=0.9",
        })
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(resp.text, "html.parser")
        for card in soup.find_all(["div", "li"], class_=True, limit=max_results * 2):
            link = card.find("a", href=True)
            if link:
                href = link.get("href", "")
                title = link.get_text(strip=True)
                if title and len(title) > 5 and href not in seen:
                    seen.add(href)
                    if not href.startswith("http"):
                        href = "https://in.indeed.com" + href
                    results.append(SearchResult(
                        source="web", source_job_id=href.split("?")[0],
                        url=href, title=title, location=location,
                    ).model_dump())
    except Exception as e:
        logger.debug("Web/Indeed failed: %s", e)

    # Source 2: Try ATS discovery for company-like terms in the query
    company_candidate = query.split()[0]
    try:
        from tools.discovery_tools import _company_to_slug
        slug = _company_to_slug(company_candidate)
        for pattern in ["https://boards.greenhouse.io/{slug}", "https://jobs.lever.co/{slug}"]:
            try:
                ats_url = pattern.format(slug=slug)
                resp = _retry_get(ats_url, timeout=8)
                from bs4 import BeautifulSoup
                soup = BeautifulSoup(resp.text, "html.parser")
                for tag in soup.find_all(["nav", "footer", "header"]):
                    tag.decompose()
                for link in soup.find_all("a", href=True, limit=max_results):
                    href = link.get("href", "")
                    title = link.get_text(strip=True)
                    if not title or len(title) < 8 or href in seen:
                        continue
                    seen.add(href)
                    if href.startswith("/"):
                        href = "/".join(ats_url.split("/")[:3]) + href
                    results.append(SearchResult(
                        source="ats", source_job_id=href,
                        url=href, title=title, company=company_candidate,
                    ).model_dump())
                break
            except Exception:
                continue
    except Exception as e:
        logger.debug("Web/ATS discovery failed: %s", e)

    logger.info("Web search: %d results for '%s'", len(results), query)
    return json.dumps({
        "results": results[:max_results],
        "error": None if results else f"No results for '{query}'"
    })


# ===========================================================================
# ATS search (Greenhouse, Lever, Ashby)
# ===========================================================================
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
