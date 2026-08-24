"""
ATS-specific job listing parsers for Greenhouse, Lever, and Ashby.

Each parser extracts structured job records from the platform's HTML,
producing normalized results with source, title, company, location, and URL.
"""

import json
import logging
import re
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; JobTracker/1.0)"}


def parse_greenhouse(url: str, company: str) -> list[dict]:
    """
    Parse Greenhouse career page into job records.

    Greenhouse lists jobs in <div class="opening"> elements containing:
    - <a> with job title and URL
    - <span class="location"> with location text
    """
    jobs = []
    try:
        resp = requests.get(url, headers=HEADERS, timeout=10)
        resp.raise_for_status()
    except requests.RequestException:
        return jobs

    soup = BeautifulSoup(resp.text, "html.parser")

    # Greenhouse openings are in div.opening elements
    for opening in soup.find_all("div", class_="opening"):
        link = opening.find("a", href=True)
        if not link:
            continue

        title = link.get_text(strip=True)
        href = link["href"]
        if not title or len(title) < 5:
            continue

        # Extract location from span.location
        location_el = opening.find("span", class_="location")
        location = location_el.get_text(strip=True) if location_el else ""

        # Extract department if available
        dept_el = opening.find("span", class_="department")
        department = dept_el.get_text(strip=True) if dept_el else ""

        full_url = urljoin(url, href)
        job_id = re.search(r"/(\d+)", href)
        source_id = f"greenhouse_{job_id.group(1)}" if job_id else href

        jobs.append({
            "source": "greenhouse",
            "source_job_id": source_id,
            "url": full_url,
            "title": title,
            "company": company,
            "location": location,
            "department": department,
        })

    logger.info("Greenhouse (%s): %d jobs", company, len(jobs))
    return jobs


def parse_lever(url: str, company: str) -> list[dict]:
    """
    Parse Lever career page into job records.

    Lever lists jobs in <div class="posting"> elements containing:
    - <a> or <h5> with job title and URL
    - <span class="location"> or <div class="location"> with location
    - <span class="department"> or <div class="workplaceTypes"> with metadata
    """
    jobs = []
    try:
        resp = requests.get(url, headers=HEADERS, timeout=10)
        resp.raise_for_status()
    except requests.RequestException:
        return jobs

    soup = BeautifulSoup(resp.text, "html.parser")

    # Lever postings are in div.posting or a.posting-title
    for posting in soup.find_all(["div", "a"], class_=re.compile(r"posting\b", re.I)):
        # Skip wrapper divs that contain child postings
        if posting.name == "div" and posting.find(class_=re.compile(r"posting\b", re.I)):
            continue

        link = posting if posting.name == "a" else posting.find("a", href=True)
        if not link:
            continue

        title = link.get_text(strip=True)
        href = link.get("href", "")
        if not title or len(title) < 5:
            continue

        # Find location in parent/sibling elements
        parent = posting.find_parent(["div", "li"]) if posting.name != "div" else posting
        location = ""
        remote_type = ""

        if parent:
            loc_el = parent.find(["span", "div"], class_=re.compile(r"location|workplace", re.I))
            if loc_el:
                location = loc_el.get_text(strip=True)

            # Detect remote/onsite
            cat_el = parent.find(["span", "div"], class_=re.compile(r"category|commitment|workplace", re.I))
            if cat_el:
                remote_type = cat_el.get_text(strip=True)

        full_url = urljoin(url, href)
        # Lever uses UUIDs as job IDs
        job_id_match = re.search(r"/([a-f0-9-]{20,})", href)
        source_id = f"lever_{job_id_match.group(1)[:12]}" if job_id_match else href

        # Combine location info
        loc_parts = [p for p in [location, remote_type] if p]
        combined_location = " — ".join(loc_parts) if loc_parts else ""

        jobs.append({
            "source": "lever",
            "source_job_id": source_id,
            "url": full_url,
            "title": title,
            "company": company,
            "location": combined_location,
        })

    logger.info("Lever (%s): %d jobs", company, len(jobs))
    return jobs


def parse_ashby(url: str, company: str) -> list[dict]:
    """
    Parse Ashby career page via their JSON API.

    Ashby exposes job listings at: {base_url}/api/job-board/{board_id}
    The HTML page also contains an embedded script with job data.
    """
    jobs = []
    try:
        resp = requests.get(url, headers=HEADERS, timeout=10)
        resp.raise_for_status()
    except requests.RequestException:
        return jobs

    # Try extracting from embedded JSON in the page
    soup = BeautifulSoup(resp.text, "html.parser")
    for script in soup.find_all("script"):
        if not script.string:
            continue
        # Ashby embeds job data in window.__NEXT_DATA__ or similar
        for pattern in [r'"jobPostings"\s*:\s*(\[.+?\])', r'"jobs"\s*:\s*(\[.+?\])']:
            match = re.search(pattern, script.string, re.DOTALL)
            if match:
                try:
                    job_list = json.loads(match.group(1))
                    for jd in job_list[:50]:
                        title = jd.get("title", "")
                        location = jd.get("location", "")
                        if isinstance(location, dict):
                            location = location.get("name", "")
                        job_url = jd.get("applyUrl") or jd.get("url", "")
                        if not job_url and jd.get("id"):
                            job_url = f"{url}/{jd['id']}"

                        jobs.append({
                            "source": "ashby",
                            "source_job_id": f"ashby_{jd.get('id', '')}",
                            "url": urljoin(url, job_url) if job_url else url,
                            "title": title,
                            "company": company,
                            "location": location,
                        })
                    logger.info("Ashby (%s): %d jobs from JSON", company, len(jobs))
                    return jobs
                except (json.JSONDecodeError, KeyError):
                    continue

    # Fallback: parse HTML links
    for link in soup.find_all("a", href=True):
        href = link["href"]
        title = link.get_text(strip=True)
        if not title or len(title) < 8:
            continue
        if "/job/" in href or "/jobs/" in href or "/open/" in href:
            jobs.append({
                "source": "ashby",
                "source_job_id": f"ashby_{href}",
                "url": urljoin(url, href),
                "title": title,
                "company": company,
                "location": "",
            })

    logger.info("Ashby (%s): %d jobs from HTML", company, len(jobs))
    return jobs


def parse_ats(url: str, company: str, platform: str) -> list[dict]:
    """Route to the correct ATS parser based on platform."""
    parsers = {
        "greenhouse": parse_greenhouse,
        "lever": parse_lever,
        "ashby": parse_ashby,
    }
    parser = parsers.get(platform)
    if parser:
        return parser(url, company)
    return []
