"""Discovery tools — find company career pages and ATS platforms."""

import json
import logging
from concurrent.futures import ThreadPoolExecutor

import requests
from langchain_core.tools import tool
from pydantic import BaseModel, Field

from tools.url_security import validate_url

logger = logging.getLogger(__name__)

# Known ATS patterns (fallback, not primary strategy)
ATS_PATTERNS = [
    ("greenhouse", "https://boards.greenhouse.io/{slug}"),
    ("lever", "https://jobs.lever.co/{slug}"),
    ("ashby", "https://jobs.ashbyhq.com/{slug}"),
]


def _company_to_slug(company: str) -> str:
    return company.lower().replace(" ", "").replace(".", "").replace("&", "").replace(",", "")


# ===========================================================================
# discover_company_career_page
# ===========================================================================

class DiscoverCareerPageInput(BaseModel):
    company: str = Field(description="Company name to find career page for")


@tool(args_schema=DiscoverCareerPageInput)
def discover_company_career_page(company: str) -> str:
    """
    Discover a company's public ATS-hosted job board (not its first-party
    careers site). Tries Greenhouse, Lever, and Ashby and returns a working URL.
    Use this only for the separate ATS-board search path.
    """
    slug = _company_to_slug(company)
    headers = {"User-Agent": "Mozilla/5.0 (compatible; JobTracker/1.0)"}

    def probe(candidate):
        ats_name, pattern = candidate
        url = pattern.format(slug=slug)
        safe, reason = validate_url(url)
        if not safe:
            return None
        probe_url = {
            "greenhouse": f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs",
            "lever": f"https://api.lever.co/v0/postings/{slug}?mode=json",
            "ashby": f"https://api.ashbyhq.com/posting-api/job-board/{slug}",
        }[ats_name]
        safe, reason = validate_url(probe_url)
        if not safe:
            return None
        try:
            resp = requests.get(probe_url, headers=headers, timeout=6)
            if resp.status_code == 200:
                data = resp.json()
                listings = data if isinstance(data, list) else data.get("jobs")
                if isinstance(listings, list):
                    return ats_name, url
        except (requests.RequestException, ValueError):
            pass
        return None

    # The three ATS probes are independent. Running them together changes no
    # decision logic and caps discovery latency at one timeout instead of three.
    with ThreadPoolExecutor(max_workers=len(ATS_PATTERNS)) as executor:
        probes = list(executor.map(probe, ATS_PATTERNS))
    for discovered in probes:
        if discovered:
            ats_name, url = discovered
            logger.info("Discovered %s career page: %s -> %s", company, ats_name, url)
            return json.dumps({
                "found": True,
                "company": company,
                "platform": ats_name,
                "career_page_url": url,
                "error": None,
            })

    return json.dumps({
        "found": False,
        "company": company,
        "career_page_url": None,
        "error": f"No ATS career page found for {company}. Try search_web_jobs instead.",
    })


# ===========================================================================
# discover_ats_platform
# ===========================================================================

class DiscoverATSInput(BaseModel):
    career_page_url: str = Field(description="URL of a potential career page to identify")


@tool(args_schema=DiscoverATSInput)
def discover_ats_platform(career_page_url: str) -> str:
    """
    Identify which ATS platform a career page URL uses (Greenhouse, Lever, Ashby, etc.)
    by inspecting the page content. Useful for unknown career page URLs.
    """
    safe, reason = validate_url(career_page_url)
    if not safe:
        return json.dumps({"platform": "unknown", "error": f"URL validation failed: {reason}"})

    headers = {"User-Agent": "Mozilla/5.0 (compatible; JobTracker/1.0)"}
    try:
        resp = requests.get(career_page_url, headers=headers, timeout=6)
        resp.raise_for_status()
    except requests.RequestException as e:
        return json.dumps({"platform": "unknown", "error": str(e)})

    text = resp.text.lower()
    platform = "generic"

    if "greenhouse" in text or "boards.greenhouse" in text:
        platform = "greenhouse"
    elif "lever.co" in text:
        platform = "lever"
    elif "ashbyhq" in text:
        platform = "ashby"
    elif "workday" in text:
        platform = "workday"
    elif "smartrecruiters" in text:
        platform = "smartrecruiters"

    return json.dumps({
        "platform": platform,
        "career_page_url": career_page_url,
        "usable": platform != "generic",
        "error": None,
    })
