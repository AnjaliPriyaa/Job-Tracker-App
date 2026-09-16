"""Read verified, company-owned career pages without visiting ATS job boards."""

import json
import logging
import re
import time
from datetime import datetime, timezone
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from tools.url_security import validate_url

logger = logging.getLogger(__name__)

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; JobTracker/1.0)"}
TITLE_PATTERN = re.compile(
    r"\b(?:devops|devsecops|sre)\b|"
    r"\b(?:site reliability|service reliability|platform|cloud|infrastructure)\s+engineer\b|"
    r"\bsoftware engineer\s*[,–-]\s*(?:infrastructure|cloud|platform)\b",
    re.IGNORECASE,
)
EXCLUDED_TITLE = re.compile(r"\b(?:staff|principal|manager|director|lead|architect|intern|junior)\b", re.I)
INDIA_LOCATION = re.compile(r"\b(?:india|bengaluru|bangalore|hyderabad|secunderabad)\b", re.I)


def _approved(url: str, hosts: list[str]) -> bool:
    safe, _ = validate_url(url)
    hostname = (urlparse(url).hostname or "").lower()
    return safe and any(
        hostname == host.lower() if not host.startswith(".")
        else hostname.endswith(host.lower())
        for host in hosts
    )


def _get_page(url: str, hosts: list[str]) -> str:
    """Follow only explicitly approved company-owned hosts, never an ATS redirect."""
    for _ in range(4):
        if not _approved(url, hosts):
            raise ValueError(f"Not a verified company-owned URL: {url}")
        response = requests.get(url, headers=HEADERS, timeout=12, allow_redirects=False)
        if response.status_code in {301, 302, 303, 307, 308}:
            location = response.headers.get("Location", "")
            if not location:
                raise ValueError(f"Redirect without a location: {url}")
            url = urljoin(url, location)
            continue
        response.raise_for_status()
        return response.text
    raise ValueError("Too many career-page redirects")


def _plain(value: str) -> str:
    return " ".join(BeautifulSoup(value or "", "html.parser").get_text(" ", strip=True).split())


def _apple_listings(html: str, page_url: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    jobs = []
    for card in soup.select("li.rc-accordion-item"):
        link = card.select_one("h3 a[href*='/details/']")
        if not link:
            continue
        location_tag = card.select_one(".job-title-location")
        excerpt_tag = card.select_one(".job-list-item.pb-30")
        location = location_tag.get_text(" ", strip=True) if location_tag else ""
        jobs.append({
            "url": urljoin(page_url, link["href"]),
            "title": link.get_text(" ", strip=True),
            "location": re.sub(r"^Location\s+", "", location, flags=re.I),
            "description": excerpt_tag.get_text(" ", strip=True) if excerpt_tag else "",
        })
    return jobs


def _apple_detail(html: str) -> dict:
    soup = BeautifulSoup(html, "html.parser")
    script = next((tag.string for tag in soup.find_all("script")
                   if tag.string and "__staticRouterHydrationData" in tag.string), None)
    if not script or "JSON.parse(" not in script:
        return {}
    try:
        encoded, _ = json.JSONDecoder().raw_decode(script.split("JSON.parse(", 1)[1])
        job = json.loads(encoded)["loaderData"]["jobDetails"]["jobsData"]
    except (ValueError, KeyError, TypeError):
        return {}
    selected = job.get("selectedLocation") or {}
    if not isinstance(selected, dict):
        selected = {}
    location = ", ".join(part for part in (
        selected.get("city"), selected.get("stateProvince"), selected.get("countryName")
    ) if part)
    # Required qualifications come first so the evaluator sees experience
    # requirements before the compact description limit is applied.
    description = " ".join(_plain(job.get(key, "")) for key in (
        "minimumQualifications", "description", "jobSummary"
    )).strip()[:2400]
    return {"title": job.get("postingTitle", ""), "location": location,
            "description": description}


def _microsoft_listings(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    jobs = []
    for card in soup.select(".careers-joblistResponsive-columnList"):
        link = card.select_one("a[href*='apply.careers.microsoft.com/careers/job/']")
        title = card.select_one("h3.careers-joblistResponsive-subheading")
        if not link or not title:
            continue
        location = card.select_one(".careers-joblistResponsive-primarylocation")
        description = card.select_one(".careers-joblistResponsive-desc")
        description_text = _plain(description.get_text(" ", strip=True)) if description else ""
        # Put actual requirements ahead of company boilerplate so a compact
        # evaluation excerpt cannot hide an over-level experience requirement.
        description_text = re.split(r"\bPreferred Qualifications\b", description_text,
                                    maxsplit=1, flags=re.I)[0]
        required = re.search(r"\bRequired Qualifications\b", description_text, re.I)
        if required:
            description_text = (description_text[required.start():required.start() + 900]
                                + " " + description_text[:1500]).strip()
        jobs.append({
            "url": link["href"],
            "title": title.get_text(" ", strip=True),
            "location": location.get_text(" ", strip=True) if location else "",
            "description": description_text[:2400],
        })
    return jobs


def _google_listings(html: str, page_url: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    jobs = []
    for card in soup.select("li.lLd3Je"):
        title = card.find("h3")
        link = card.find("a", href=re.compile(r"jobs/results/\d+"))
        location = card.select_one(".r0wTof")
        if not title or not link or not location:
            continue
        href = link["href"]
        if href.startswith("jobs/results/"):
            href = href.removeprefix("jobs/results/")
        minimum = card.select_one(".Xsxa1e")
        jobs.append({
            "url": urljoin(page_url, href),
            "title": title.get_text(" ", strip=True),
            "location": location.get_text(" ", strip=True),
            "description": minimum.get_text(" ", strip=True) if minimum else "",
        })
    return jobs


def _google_detail(html: str) -> dict:
    soup = BeautifulSoup(html, "html.parser")
    required = next((tag for tag in soup.find_all("h3")
                     if tag.get_text(" ", strip=True).lower().startswith(
                         "minimum qualifications")), None)
    minimum = required.find_next_sibling("ul") if required else None
    about = soup.select_one(".aG5W3")
    responsibilities = soup.select_one(".BDNOWe")
    description = " ".join(tag.get_text(" ", strip=True) for tag in (
        minimum, about, responsibilities
    ) if tag).strip()[:2400]
    return {"description": description} if description else {}


def _jsonld_listings(html: str) -> list[dict]:
    """Generic fallback for first-party pages exposing schema.org JobPosting."""
    soup = BeautifulSoup(html, "html.parser")
    jobs = []

    def objects(value):
        if isinstance(value, list):
            for item in value:
                yield from objects(item)
        elif isinstance(value, dict):
            types = value.get("@type", [])
            if isinstance(types, str):
                types = [types]
            if "JobPosting" in types:
                yield value
            yield from objects(value.get("@graph", []))
            yield from objects(value.get("mainEntity", []))

    for script in soup.select('script[type="application/ld+json"]'):
        try:
            data = json.loads(script.string or script.get_text())
        except (ValueError, TypeError):
            continue
        for posting in objects(data):
            place = posting.get("jobLocation") or {}
            if isinstance(place, list):
                place = place[0] if place else {}
            address = place.get("address") or {} if isinstance(place, dict) else {}
            if isinstance(address, str):
                location = address
            else:
                location = ", ".join(str(address.get(key, "")) for key in (
                    "addressLocality", "addressRegion", "addressCountry"
                ) if address.get(key))
            jobs.append({
                "url": posting.get("url", ""),
                "title": posting.get("title", ""),
                "location": location,
                "description": _plain(posting.get("description", ""))[:2400],
                "validThrough": posting.get("validThrough", ""),
                "hiringOrganization": posting.get("hiringOrganization", {}),
            })
    return jobs


_NAVIGATION = re.compile(r"\b(?:search|browse|view|explore|open)\s+(?:all\s+)?(?:jobs|roles|positions|openings)\b", re.I)
_JOB_PATH = re.compile(r"/(?:job|jobs|role|roles|position|positions|career|careers)(?:/|$|\?)", re.I)
_CLOSED = re.compile(
    r"(?:job|position|role).{0,100}(?:filled|closed|no longer available)|"
    r"(?:not|no longer) accepting (?:new )?applications",
    re.I,
)


def _generic_links(html: str, page_url: str, hosts: list[str]) -> tuple[list[dict], list[str]]:
    """Read role links and one useful next page from a company-owned page."""
    soup = BeautifulSoup(html, "html.parser")
    candidates = _jsonld_listings(html)
    navigation = []
    for link in soup.find_all("a", href=True, limit=350):
        url = urljoin(page_url, link["href"]).split("#", 1)[0]
        parsed = urlparse(url)
        career_host = (parsed.hostname or "").startswith(("careers.", "jobs."))
        if not _approved(url, hosts) or not (career_host or _JOB_PATH.search(parsed.path)):
            continue
        label = link.get_text(" ", strip=True)
        if TITLE_PATTERN.search(label) and not EXCLUDED_TITLE.search(label):
            card = link.find_parent(["article", "li"]) or link.parent
            nearby = card.get_text(" ", strip=True)[:350] if card else ""
            candidates.append({"url": url, "title": label, "location": nearby,
                               "description": ""})
        elif _NAVIGATION.search(label) and url != page_url:
            navigation.append(url)
    return candidates, list(dict.fromkeys(navigation))[:2]


def _generic_detail(html: str, url: str) -> dict:
    """Require structured job evidence or a substantial first-party job page."""
    if _CLOSED.search(BeautifulSoup(html, "html.parser").get_text(" ", strip=True)[:5000]):
        return {}
    postings = _jsonld_listings(html)
    if postings:
        exact = next((job for job in postings if job.get("url", "").split("?", 1)[0]
                      == url.split("?", 1)[0]), postings[0])
        valid_through = exact.get("validThrough", "")
        if valid_through:
            try:
                expires = datetime.fromisoformat(valid_through.replace("Z", "+00:00"))
                if expires.tzinfo is None:
                    expires = expires.replace(tzinfo=timezone.utc)
                if expires < datetime.now(timezone.utc):
                    return {}
            except ValueError:
                pass
        return exact
    soup = BeautifulSoup(html, "html.parser")
    heading = soup.find("h1")
    main = soup.find("main") or soup.find("article")
    if not heading or not main or not _JOB_PATH.search(urlparse(url).path):
        return {}
    title = heading.get_text(" ", strip=True)
    text = main.get_text(" ", strip=True)
    # Generic HTML is less trustworthy than JobPosting JSON-LD. Require an
    # explicit India location near the title and enough substantive content.
    location_tag = main.find(attrs={"class": re.compile("location", re.I)})
    location_text = location_tag.get_text(" ", strip=True) if location_tag else ""
    if not location_text:
        location_tag = main.find(attrs={"itemprop": "jobLocation"})
        location_text = location_tag.get_text(" ", strip=True) if location_tag else ""
    location = ""
    location_match = INDIA_LOCATION.search(location_text)
    if location_match:
        location = location_match.group(0)
    if not TITLE_PATTERN.search(title) or not location or len(text) < 250:
        return {}
    return {"title": title, "location": location, "description": text[:2400]}


def _generic_first_party_jobs(company: str, site: dict, max_results: int) -> list[dict]:
    """Bounded observe/verify loop for first-party sites without a custom adapter."""
    hosts = site["allowed_hosts"]
    queue = list(site["pages"][:2])
    visited = set()
    candidates = []
    successful_pages = 0
    deadline = time.monotonic() + 18
    while queue and len(visited) < 3 and time.monotonic() < deadline:
        url = queue.pop(0)
        if url in visited:
            continue
        visited.add(url)
        try:
            html = _get_page(url, hosts)
        except (requests.RequestException, ValueError) as exc:
            logger.info("Career source unavailable for %s: %s", company, exc)
            continue
        successful_pages += 1
        found, navigation = _generic_links(html, url, hosts)
        candidates.extend(found)
        if not found:
            queue.extend(item for item in navigation if item not in visited)
    if successful_pages == 0:
        raise ValueError(f"No reachable first-party career page for {company}")

    verified = []
    seen = set()
    for candidate in candidates[:min(max_results * 3, 9)]:
        if time.monotonic() >= deadline:
            break
        url = candidate.get("url", "").split("#", 1)[0]
        if not _approved(url, hosts) or url in seen:
            continue
        seen.add(url)
        try:
            detail = _generic_detail(_get_page(url, hosts), url)
        except (requests.RequestException, ValueError) as exc:
            logger.info("Career job detail unavailable for %s: %s", company, exc)
            continue
        title = detail.get("title", "")
        location = detail.get("location", "")
        description = detail.get("description", "")
        if (not TITLE_PATTERN.search(title) or EXCLUDED_TITLE.search(title)
                or not INDIA_LOCATION.search(location) or len(description) < 120):
            continue
        verified.append({"url": url, "title": title, "location": location,
                         "description": description[:2400], "company": company,
                         "source": "company_career",
                         "source_job_id": re.sub(r"[^a-z0-9]+", "", company.lower())
                         + ":" + urlparse(url).path.rstrip("/")
                         + ("?" + urlparse(url).query if urlparse(url).query else "")})
        if len(verified) >= max_results:
            break
    return verified


def first_party_jobs(company: str, site: dict, max_results: int) -> list[dict]:
    """Return relevant India jobs from configured official pages only."""
    hosts = site.get("allowed_hosts", [])
    pages = site.get("pages", [])[:4]
    if not hosts or not pages:
        return []
    if site.get("strategy") == "generic":
        return _generic_first_party_jobs(company, site, max_results)
    results = []
    seen_urls = set()
    for page_url in pages:
        try:
            html = _get_page(page_url, hosts)
        except (requests.RequestException, ValueError) as exc:
            logger.warning("Company career page failed for %s: %s", company, exc)
            continue
        if company == "Apple":
            listings = _apple_listings(html, page_url)
        elif company == "Microsoft":
            listings = _microsoft_listings(html)
        elif company == "Google":
            listings = _google_listings(html, page_url)
        else:
            listings = _jsonld_listings(html)
        for job in listings:
            url = job.get("url", "").split("#", 1)[0]
            identity = (urlparse(url).hostname, urlparse(url).path.rstrip("/"))
            if (not _approved(url, hosts) or identity in seen_urls
                    or not TITLE_PATTERN.search(job.get("title", ""))
                    or EXCLUDED_TITLE.search(job.get("title", ""))
                    or not INDIA_LOCATION.search(job.get("location", ""))):
                continue
            seen_urls.add(identity)
            job["url"] = url
            results.append(job)

    # A listing without a live detail page is not a verified open role.
    verified = []
    for job in results:
        if len(verified) >= max_results:
            break
        if company in {"Apple", "Google"}:
            try:
                html = _get_page(job["url"], hosts)
                detail = _apple_detail(html) if company == "Apple" else _google_detail(html)
                if not detail.get("description"):
                    continue
                job.update({key: value for key, value in detail.items() if value})
            except (requests.RequestException, ValueError) as exc:
                logger.warning("%s job detail failed: %s", company, exc)
                continue
        elif not job.get("description"):
            continue
        job["company"] = company
        job["source"] = "company_career"
        job["source_job_id"] = (
            re.sub(r"[^a-z0-9]+", "", company.lower()) + ":" +
            urlparse(job["url"]).path.rstrip("/")
        )
        job["description"] = job.get("description", "")[:2400]
        verified.append(job)
    return verified
