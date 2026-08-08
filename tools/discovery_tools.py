"""Discovery tools — find company career pages and ATS platforms."""

import json
import logging

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
    Discover where a company hosts its job listings. Tries known ATS platforms
    (Greenhouse, Lever, Ashby) and returns the working URL.
    Use this when you want to find jobs at a specific company.
    """
    slug = _company_to_slug(company)
    headers = {"User-Agent": "Mozilla/5.0 (compatible; JobTracker/1.0)"}

    for ats_name, pattern in ATS_PATTERNS:
        url = pattern.format(slug=slug)
        safe, reason = validate_url(url)
        if not safe:
            continue
        try:
            resp = requests.get(url, headers=headers, timeout=8)
            if resp.status_code == 200 and len(resp.text) > 5000:
                logger.info("Discovered %s career page: %s → %s", company, ats_name, url)
                return json.dumps({
                    "found": True,
                    "company": company,
                    "platform": ats_name,
                    "career_page_url": url,
                    "error": None,
                })
        except requests.RequestException:
            continue

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
        resp = requests.get(career_page_url, headers=headers, timeout=8)
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
