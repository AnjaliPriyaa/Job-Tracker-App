"""Search tools with typed Pydantic schemas."""

import json
import logging
import re
import time

import requests
from langchain_core.tools import tool
from pydantic import BaseModel, Field

from models.search import SearchResult
from storage import JobRepository

logger = logging.getLogger(__name__)

RETRY_MAX = 1
RETRY_BACKOFF = 1.5
MAX_RESULTS_PER_SEARCH = int(__import__("os").getenv("MAX_RESULTS_PER_SEARCH", "12"))


def _canonical_identity(result: dict) -> tuple[str, str, str]:
    """Normalize cross-source IDs so aggregator links deduplicate early."""
    source = str(result.get("source", "web"))
    source_job_id = str(result.get("source_job_id", ""))
    url = str(result.get("url", ""))
    linkedin_match = re.search(r"linkedin\.com/jobs/view/(\d+)", url)
    if linkedin_match:
        canonical_source = "linkedin"
        canonical_source_id = linkedin_match.group(1)
    else:
        canonical_source = source
        canonical_source_id = source_job_id or url.split("?", 1)[0]
    return source, source_job_id, f"{canonical_source}:{canonical_source_id}"


def _compact_result(result: dict, canonical_id: str) -> dict:
    keys = ("source", "source_job_id", "url", "title", "company", "location")
    compact = {key: result[key] for key in keys if result.get(key)}
    compact["canonical_id"] = canonical_id
    return compact


def _deduplicate_and_store(results: list[dict], max_results: int) -> tuple[list[dict], int]:
    """Persist discoveries and return only candidates unseen by this database."""
    unseen: list[dict] = []
    duplicates = 0
    for result in results:
        source, source_job_id, candidate_id = _canonical_identity(result)
        url = str(result.get("url", ""))
        existing = (
            JobRepository.find_by_source(source, source_job_id)
            or JobRepository.find(candidate_id)
            or JobRepository.find_by_url(url)
        )
        if not existing and result.get("company") and result.get("title"):
            existing = JobRepository.find_by_secondary(
                str(result.get("company", "")),
                str(result.get("title", "")),
                str(result.get("location", "")),
            )

        canonical_id = existing or candidate_id
        JobRepository.upsert(
            canonical_id,
            str(result.get("company", "")),
            str(result.get("title", "")),
            str(result.get("location", "")),
            source,
            source_job_id,
            url,
            str(result.get("snippet", "")),
        )
        if existing:
            duplicates += 1
            continue
        unseen.append(_compact_result(result, canonical_id))
        if len(unseen) >= min(max_results, MAX_RESULTS_PER_SEARCH):
            break
    return unseen, duplicates


def _search_payload(results: list[dict], max_results: int, error: str | None = None,
                    **metadata) -> str:
    unseen, duplicates = _deduplicate_and_store(results, max_results)
    payload = {
        "results": unseen,
        "new_count": len(unseen),
        "duplicates_filtered": duplicates,
        "error": error if not unseen else None,
        **metadata,
    }
    return json.dumps(payload, separators=(",", ":"))


def _retry_get(url: str, timeout: int = 10, extra_headers: dict | None = None) -> requests.Response:
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
    max_results: int = Field(default=12, ge=1, le=25)


@tool(args_schema=LinkedInSearchInput)
def search_linkedin(url: str, max_results: int = 12) -> str:
    """
    Search LinkedIn for jobs. Provide a LinkedIn search URL. Returns structured job results.
    Use this for broad searches like "DevOps engineer in Bengaluru".
    """
    try:
        resp = _retry_get(url, timeout=10)
    except requests.RequestException as e:
        return json.dumps({"results": [], "error": f"LinkedIn request failed: {e}"})

    from pathlib import Path
    from bs4 import BeautifulSoup
    from policies.job_policy import is_target_company

    raw_html = resp.text
    results: list[dict] = []
    seen: set[str] = set()
    soup = BeautifulSoup(raw_html, "html.parser")
    for card in soup.find_all(attrs={"data-entity-urn": re.compile(r"urn:li:jobPosting:\d+")}):
        job_id = card.get("data-entity-urn", "").rsplit(":", 1)[-1]
        if job_id in seen or not job_id.isdigit():
            continue
        seen.add(job_id)
        title_tag = card.find("h3", class_="base-search-card__title")
        company_tag = card.find("h4", class_="base-search-card__subtitle")
        location_tag = card.find("span", class_="job-search-card__location")
        results.append(SearchResult(
            source="linkedin",
            source_job_id=job_id,
            url=f"https://www.linkedin.com/jobs/view/{job_id}",
            title=title_tag.get_text(" ", strip=True) if title_tag else "",
            company=company_tag.get_text(" ", strip=True) if company_tag else "",
            location=location_tag.get_text(" ", strip=True) if location_tag else "",
        ).model_dump())

    if not results:
        # Fallback for a LinkedIn layout without structured search cards.
        for match in re.finditer(r"urn:li:jobPosting:(\d{7,15})|/jobs/view/(\d{7,15})", raw_html):
            job_id = match.group(1) or match.group(2)
            if job_id not in seen and len(results) < max_results:
                seen.add(job_id)
                results.append(SearchResult(
                    source="linkedin",
                    source_job_id=job_id,
                    url=f"https://www.linkedin.com/jobs/view/{job_id}",
                ).model_dump())

    if results:
        with open(Path(__file__).resolve().parent.parent / "config.json") as config_file:
            targets = json.load(config_file).get("target_companies", [])
        role_pattern = re.compile(
            r"\b(?:devops|devsecops|sre)\b|"
            r"\b(?:site reliability|platform|cloud|infrastructure)\s+engineer\b|"
            r"\bsoftware engineer\s*[,–-]\s*(?:infrastructure|cloud|platform)\b",
            re.IGNORECASE,
        )
        excluded = re.compile(r"\b(?:staff|principal|manager|director|lead|architect|intern|junior)\b", re.I)
        results.sort(key=lambda result: (
            bool(result.get("company") and is_target_company(result["company"], targets))
            and bool(role_pattern.search(result.get("title", "")))
            and not bool(excluded.search(result.get("title", ""))),
            bool(result.get("company") and is_target_company(result["company"], targets)),
            bool(role_pattern.search(result.get("title", ""))),
        ), reverse=True)

    logger.info("LinkedIn search: %d raw results", len(results))
    return _search_payload(
        results[:max_results],
        max_results,
        None if results else "No job IDs found",
    )


# ===========================================================================
# Web search (broad fallback / discovery)
# ===========================================================================

class WebSearchInput(BaseModel):
    query: str = Field(description="Search query for jobs, e.g. 'DevOps engineer Bengaluru'")
    location: str = Field(default="India", description="Location filter")
    max_results: int = Field(default=10, ge=1, le=25)


@tool(args_schema=WebSearchInput)
def search_web_jobs(query: str, location: str = "India", max_results: int = 10) -> str:
    """
    Broad web-based job discovery. Searches multiple job aggregators,
    career platforms, and ATS sources. Use when platform-specific tools
    don't find enough results or when discovering new sources.
    """
    results: list[dict] = []
    seen: set[str] = set()
    q = requests.utils.quote(query)
    loc_q = requests.utils.quote(location)

    # Source 1: Indeed India
    try:
        indeed_url = f"https://in.indeed.com/jobs?q={q}&l={loc_q}&fromage=7"
        resp = _retry_get(indeed_url, timeout=10, extra_headers={
            "Accept": "text/html",
            "Accept-Language": "en-US,en;q=0.9",
        })
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(resp.text, "html.parser")
        for link in soup.find_all("a", href=True, limit=max_results * 2):
            href = link.get("href", "")
            title = link.get_text(strip=True)
            if title and len(title) > 8 and "indeed" in href.lower():
                if href not in seen:
                    seen.add(href)
                    if not href.startswith("http"):
                        href = "https://in.indeed.com" + href
                    results.append(SearchResult(
                        source="indeed", source_job_id=href.split("?")[0],
                        url=href, title=title, location=location,
                    ).model_dump())
        logger.debug("Indeed: %d results", len([r for r in results if r["source"] == "indeed"]))
    except Exception as e:
        logger.debug("Web/Indeed: %s", e)

    # Source 2: Google Jobs via direct search (structured data in HTML)
    try:
        google_url = f"https://www.google.com/search?q=site:linkedin.com/jobs+{q}+{loc_q}&ibp=htl;jobs"
        resp = _retry_get(google_url, timeout=8, extra_headers={
            "Accept": "text/html",
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
        })
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(resp.text, "html.parser")
        # Google Jobs results are in g-card or div[data-hveid] elements
        for link in soup.find_all("a", href=True, limit=max_results):
            href = link.get("href", "")
            title = link.get_text(strip=True)
            if "/jobs/view/" in href and title and len(title) > 8:
                jid_match = re.search(r"/jobs/view/(\d+)", href)
                if jid_match and jid_match.group(1) not in seen:
                    seen.add(jid_match.group(1))
                    results.append(SearchResult(
                        source="google_jobs", source_job_id=jid_match.group(1),
                        url=f"https://www.linkedin.com/jobs/view/{jid_match.group(1)}",
                        title=title, location=location,
                    ).model_dump())
        logger.debug("Google Jobs: %d results", len([r for r in results if r["source"] == "google_jobs"]))
    except Exception as e:
        logger.debug("Web/Google: %s", e)

    logger.info("Web search '%s': %d results from %d sources",
                query, len(results), len(set(r["source"] for r in results)))
    return _search_payload(
        results,
        max_results,
        None if results else f"No results for '{query}'",
        sources_searched=sorted(set(r["source"] for r in results)),
    )


# ===========================================================================
# ATS search (Greenhouse, Lever, Ashby)
# ===========================================================================
# ===========================================================================

class ATSSearchInput(BaseModel):
    company: str = Field(description="Company name to search for")
    ats_url: str = Field(description="ATS career page URL (e.g., https://boards.greenhouse.io/airbnb)")
    max_results: int = Field(default=12, ge=1, le=25)


@tool(args_schema=ATSSearchInput)
def search_ats(company: str, ats_url: str, max_results: int = 12) -> str:
    """
    Search a company's ATS (Greenhouse, Lever, Ashby) career page for jobs.
    Requires the ATS URL from discover_company_career_page.
    """
    # Determine ATS platform from URL
    platform = "generic"
    if "greenhouse" in ats_url:
        platform = "greenhouse"
    elif "lever.co" in ats_url:
        platform = "lever"
    elif "ashby" in ats_url:
        platform = "ashby"

    from tools.ats_parsers import parse_ats
    jobs = parse_ats(ats_url, company, platform)

    if jobs:
        # Large career boards often list unrelated/global openings first. Put
        # relevant India roles ahead of them before applying the result cap.
        role_terms = ("devops", "devsecops", "site reliability", "sre", "platform",
                      "cloud", "infrastructure")
        location_terms = ("bengaluru", "bangalore", "hyderabad", "india")
        excluded_terms = ("staff", "principal", "manager", "director", "lead",
                          "architect", "intern", "junior")
        jobs.sort(key=lambda job: (
            any(term in job.get("title", "").lower() for term in role_terms)
            and not any(term in job.get("title", "").lower() for term in excluded_terms)
            and any(term in job.get("location", "").lower() for term in location_terms),
            any(term in job.get("title", "").lower() for term in role_terms)
            and not any(term in job.get("title", "").lower() for term in excluded_terms),
        ), reverse=True)
        results = [SearchResult(
            source=f"ats_{platform}",
            source_job_id=j["source_job_id"],
            url=j["url"],
            title=j["title"],
            company=company,
            location=j.get("location", ""),
            snippet=j.get("description", ""),
        ).model_dump() for j in jobs[:max_results]]
        return _search_payload(results, max_results)

    # Fallback: generic link extraction
    try:
        resp = _retry_get(ats_url, timeout=10)
    except requests.RequestException as e:
        return json.dumps({"results": [], "error": f"ATS request failed: {e}"})
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(resp.text, "html.parser")
    for tag in soup.find_all(["nav", "footer", "header", "script", "style"]):
        tag.decompose()
    results: list[dict] = []
    seen_urls: set[str] = set()
    for link in soup.find_all("a", href=True, limit=max_results):
        href = link.get("href", "")
        title = link.get_text(strip=True)
        if not title or len(title) < 8 or href in seen_urls:
            continue
        seen_urls.add(href)
        if not href.startswith("http"):
            href = "/".join(ats_url.split("/")[:3]) + href
        results.append(SearchResult(
            source="ats", source_job_id=href,
            url=href, title=title, company=company,
        ).model_dump())
    return _search_payload(
        results,
        max_results,
        None if results else f"No jobs at {ats_url}",
    )
