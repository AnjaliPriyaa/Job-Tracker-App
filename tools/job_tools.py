"""Job inspection tools — fetch and extract job details."""

import json
import logging
import re
import time

import requests
from bs4 import BeautifulSoup
from langchain_core.tools import tool
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

RETRY_MAX = 2


# ===========================================================================
# fetch_job
# ===========================================================================

class FetchJobInput(BaseModel):
    url: str = Field(description="Job posting URL to fetch details from")
    source: str = Field(default="linkedin", description="Source hint: linkedin, greenhouse, lever, generic")


@tool(args_schema=FetchJobInput)
def fetch_job(url: str, source: str = "linkedin") -> str:
    """
    Fetch the full job description from a job posting URL. Extracts company name,
    job title, location, and description text automatically.
    """
    from tools.url_security import validate_url
    safe, reason = validate_url(url)
    if not safe:
        return json.dumps({"error": f"URL validation failed: {reason}", "company": "", "title": "", "location": "", "description": ""})

    headers = {"User-Agent": "Mozilla/5.0 (compatible; JobTracker/1.0)"}
    last_exc = None
    for attempt in range(RETRY_MAX + 1):
        try:
            resp = requests.get(url, headers=headers, timeout=15)
            resp.raise_for_status()
            break
        except requests.RequestException as exc:
            last_exc = exc
            if attempt < RETRY_MAX:
                time.sleep(2 ** attempt)
    else:
        return json.dumps({"error": f"Failed to fetch {url}: {last_exc}", "company": "", "title": "", "location": "", "description": ""})

    soup = BeautifulSoup(resp.text, "html.parser")
    company = ""
    title = ""
    location = ""

    # Extract from page title: "Company hiring Title in Location | LinkedIn"
    if soup.title:
        title_text = soup.title.get_text(strip=True)
        m = re.search(r'^(.+?)\s+hiring\s+(.+?)\s+in\s+(.+?)\s*\|', title_text)
        if not m:
            m = re.search(r'^(.+?)\s+hiring\s+(.+?)\s*\|', title_text)
        if m:
            company = m.group(1).strip()
            title = m.group(2).strip()
            if m.lastindex and m.lastindex >= 3:
                location = m.group(3).strip() if m.lastindex >= 3 else ""

    # Fallback: og:description
    if not company:
        og = soup.find("meta", property="og:description")
        if og and og.get("content"):
            parts = og["content"].split("·")
            company = parts[0].strip() if parts else ""

    # Description
    description = ""
    for cls in ["show-more-less-html__markup", "jobs-description__content", "description__text"]:
        el = soup.find("div", class_=cls)
        if el:
            description = el.get_text(separator="\n", strip=True)[:4000]
            break

    if not description:
        art = soup.find("article")
        if art:
            description = art.get_text(separator="\n", strip=True)[:4000]

    if not description:
        description = soup.get_text()[:4000]

    return json.dumps({
        "company": company,
        "title": title,
        "location": location,
        "description": description,
        "url": url,
        "source": source,
        "error": None,
    })


# ===========================================================================
# extract_job_details
# ===========================================================================

class ExtractJobDetailsInput(BaseModel):
    description: str = Field(description="Raw job description text")


@tool(args_schema=ExtractJobDetailsInput)
def extract_job_details(description: str) -> str:
    """
    Extract structured details from raw job description text.
    Returns: experience requirement, skills mentioned, employment type hints.
    """
    text = description.lower()
    details = {"experience_required": "", "skills": [], "employment_type": "", "remote": "unknown"}

    # Experience
    exp_range = re.search(r"(\d+)\s*[-–]\s*(\d+)\s*years?", text)
    exp_plus = re.search(r"(\d+)\+\s*years?", text)
    exp_min = re.search(r"(?:minimum|at least|min\.?)\s*(?:of\s+)?(\d+)\s*years?", text)
    if exp_range:
        details["experience_required"] = f"{exp_range.group(1)}-{exp_range.group(2)} years"
    elif exp_plus:
        details["experience_required"] = f"{exp_plus.group(1)}+ years"
    elif exp_min:
        details["experience_required"] = f"{exp_min.group(1)}+ years"

    # Skills
    skill_keywords = [
        "kubernetes", "docker", "terraform", "ansible", "aws", "azure", "gcp",
        "jenkins", "github actions", "ci/cd", "python", "linux", "prometheus",
        "grafana", "elk", "splunk", "datadog", "git", "bash", "go", "rust",
    ]
    details["skills"] = sorted(set(kw for kw in skill_keywords if kw in text))

    # Remote
    if "remote" in text:
        details["remote"] = "yes"
    elif any(w in text for w in ["onsite", "on-site", "in office"]):
        details["remote"] = "no"
    elif any(w in text for w in ["hybrid"]):
        details["remote"] = "hybrid"

    # Employment type
    if "full-time" in text or "full time" in text:
        details["employment_type"] = "full-time"
    elif "contract" in text:
        details["employment_type"] = "contract"

    # Location normalization
    details["location"] = _normalize_location(description)

    # Title normalization (if available)
    details["normalized_title"] = _normalize_title("")

    return json.dumps(details)


# ===========================================================================
# Normalization helpers (exported for reuse)
# ===========================================================================

LOCATION_MAP = {
    "bangalore": "Bengaluru",
    "bengaluru": "Bengaluru",
    "bengaluru, karnataka": "Bengaluru",
    "bangalore, india": "Bengaluru",
    "bangalore urban": "Bengaluru",
    "hyderabad": "Hyderabad",
    "secunderabad": "Hyderabad",
    "greater hyderabad": "Hyderabad",
}

LOCATION_KEYWORDS = {
    "remote": "Remote",
    "hybrid": "Hybrid",
    "onsite": "On-site",
    "on-site": "On-site",
    "work from home": "Remote",
    "wfh": "Remote",
}


def _normalize_location(text: str) -> str:
    """Normalize location strings to canonical forms."""
    text_lower = text.lower()
    for keyword, canonical in LOCATION_KEYWORDS.items():
        if keyword in text_lower:
            return canonical
    for variant, canonical in LOCATION_MAP.items():
        if variant in text_lower:
            return canonical
    if "india" in text_lower:
        return "India"
    return ""


TITLE_NORMALIZE_MAP = {
    "sr.": "Senior",
    "sr ": "Senior ",
    "senior": "Senior",
    "lead": "Lead",
    "principal": "Principal",
    "staff": "Staff",
    "associate": "Associate",
    "junior": "Junior",
    "jr.": "Junior",
    "jr ": "Junior ",
    "intern": "Intern",
}


def _normalize_title(title: str) -> str:
    """Normalize job title to a canonical form."""
    if not title:
        return ""
    t = title.strip()
    for variant, canonical in sorted(TITLE_NORMALIZE_MAP.items(), key=lambda x: -len(x[0])):
        t = re.sub(rf'\b{re.escape(variant)}\b', canonical, t, flags=re.IGNORECASE)
    # Remove location suffixes like ", Bengaluru" or " - Bangalore"
    t = re.sub(r'\s*[,–-]\s*(?:Bengaluru|Bangalore|Hyderabad|India|Remote).*$', '', t, flags=re.IGNORECASE)
    return t.strip()
