"""
Career Pages job tracker — processes jobs ON-THE-FLY.

Scrapes each company's career page → immediately fetches descriptions →
matches with DeepSeek → notifies Telegram → then moves to next company.

This avoids the "collect 898 jobs first, then process" bottleneck.
"""

import json
import logging
import os
import re
import sys
import time

import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("career_pages")

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

from utils import load_config, load_seen_jobs, save_seen_jobs, is_valid_location
from langchain_ai import JobMatcher

config = load_config()
matcher = JobMatcher()

target_companies = config.get("target_companies", [])
target_roles = config.get("roles", [])
keywords = config.get("job_portals", [{}])[0].get("keywords", [])
exclude_keywords = config.get("exclude_keywords", [])
exclude_roles = config.get("exclude_roles", [])
exclude_levels = config.get("exclude_levels", [])
max_exp = config.get("experience_years", 6)
min_exp = config.get("min_experience_years", 4)
confidence_threshold = config.get("confidence_threshold", 0.6)
seen_jobs = load_seen_jobs()

RETRY_MAX = 2
ATS_PATTERNS = [
    "https://boards.greenhouse.io/{slug}",
    "https://jobs.lever.co/{slug}",
    "https://jobs.ashbyhq.com/{slug}",
]

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _retry_get(url, timeout=10):
    headers = {"User-Agent": "Mozilla/5.0 (compatible; JobTracker/1.0)"}
    for attempt in range(RETRY_MAX + 1):
        try:
            resp = requests.get(url, headers=headers, timeout=timeout)
            resp.raise_for_status()
            return resp
        except requests.RequestException as e:
            if attempt < RETRY_MAX:
                time.sleep(2 ** attempt)
            else:
                raise e


def _company_to_slug(company):
    return company.lower().replace(" ", "").replace(".", "").replace("&", "")


def fetch_description(job_url):
    """Get job description and extract company/title from page."""
    try:
        resp = _retry_get(job_url, timeout=10)
        soup = BeautifulSoup(resp.text, "html.parser")

        company = ""
        title = ""
        if soup.title:
            title_text = soup.title.get_text(strip=True)
            m = re.search(r'^(.+?)\s+hiring\s+(.+?)\s+(?:in\s+)?', title_text)
            if m:
                company = m.group(1).strip()
                title = m.group(2).strip().rstrip("|").strip()

        desc = ""
        for cls in ["show-more-less-html__markup", "jobs-description__content"]:
            el = soup.find("div", class_=cls)
            if el:
                desc = el.get_text(separator="\n", strip=True)[:4000]
                break
        if not desc:
            desc = soup.get_text()[:4000]

        return {"description": desc, "company": company, "title": title}
    except Exception as e:
        logger.debug("  ⚠ Description fetch failed: %s", e)
        return None


def send_telegram(title, company, url, reason, source_label=""):
    """Send Telegram notification."""
    token = os.getenv("TELEGRAM_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        return False

    reason_short = reason[:120] + ("..." if len(reason) > 120 else "")
    msg = f"🔔 *{title or 'New Job'}*\n🏢 {company}"
    if source_label:
        msg += f"\n📌 {source_label}"
    msg += f"\n🔗 {url}\n_{reason_short}_"

    try:
        resp = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": msg, "parse_mode": "Markdown"},
            timeout=10,
        )
        return resp.status_code == 200 and resp.json().get("ok", False)
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Main: scrape → match → notify ON THE FLY
# ---------------------------------------------------------------------------

def main():
    total_jobs = 0
    total_matched = 0
    total_notified = 0

    companies_to_check = target_companies[:50]
    logger.info("Processing %d company career pages on-the-fly...", len(companies_to_check))

    for company in companies_to_check:
        slug = _company_to_slug(company)
        found = False

        for pattern in ATS_PATTERNS:
            url = pattern.format(slug=slug)
            try:
                resp = _retry_get(url, timeout=10)
            except requests.RequestException:
                continue

            soup = BeautifulSoup(resp.text, "html.parser")

            # Remove nav/footer/header — they contain non-job links
            for tag in soup.find_all(["nav", "footer", "header", "script", "style"]):
                tag.decompose()

            company_jobs = 0
            company_matched = 0

            # Skip words/phrases that are never job titles
            skip_words = [
                "department", "location", "team", "view all", "privacy",
                "terms", "sitemap", "english", "français", "deutsch",
                "apply now", "candidate privacy", "job search",
                "life at", "careers at", "anthem", "copyright",
                "accessibility", "cookie", "legal", "press", "blog",
                "sign in", "log in", "contact", "about", "news",
                "view docs", "view open roles", "learn more", "open roles",
                "techno-optimists", "engineering blog", "find cont",
                "read more", "get started", "subscribe", "follow us",
                "see all jobs", "all openings", "current openings",
            ]
            # Words that suggest a real job title (must have at least one)
            job_title_keywords = [
                "engineer", "devops", "sre", "cloud", "infrastructure",
                "platform", "site reliability", "developer", "architect",
                "security", "sysadmin", "administrator", "network",
                "kubernetes", "terraform", "aws", "azure", "gcp",
            ]

            for link in soup.find_all("a", href=True):
                href = link.get("href", "")
                title = link.get_text(strip=True)

                if not title or len(title) < 8:
                    continue
                title_lower = title.lower()
                if any(s in title_lower for s in skip_words):
                    continue
                # Skip links that look like URLs or navigation
                if title.startswith(("http", "//", "#", "+")):
                    continue
                if re.match(r'^[A-Z][a-z]+$', title):  # Single word like "English"
                    continue
                # Quick keyword pre-filter: must contain at least one job-related word
                if not any(kw in title_lower for kw in job_title_keywords):
                    continue

                if href.startswith("/"):
                    href = "/".join(url.split("/")[:3]) + href

                job_id = f"cp_{hash(href)}"
                if job_id in seen_jobs:
                    continue

                total_jobs += 1
                company_jobs += 1
                seen_jobs.add(job_id)

                # --- ON THE FLY: fetch description immediately ---
                desc_data = fetch_description(href)
                if not desc_data or not desc_data.get("description"):
                    continue

                actual_company = desc_data.get("company") or company
                actual_title = desc_data.get("title") or title

                # --- Company check ---
                if not any(tc.lower() in actual_company.lower() for tc in target_companies):
                    continue

                # --- Location check ---
                if not is_valid_location(desc_data["description"]):
                    logger.debug("  ✗ Non-India location: %s at %s", actual_title, actual_company)
                    continue

                # --- AI Match ---
                result = matcher.match(
                    title=actual_title,
                    company=actual_company,
                    description=desc_data["description"],
                    keywords=keywords,
                    target_companies=target_companies,
                    target_roles=target_roles,
                    exclude_keywords=exclude_keywords,
                    exclude_roles=exclude_roles,
                    exclude_levels=exclude_levels,
                    max_experience=max_exp,
                    min_experience=min_exp,
                )

                if result.match and result.confidence >= confidence_threshold:
                    total_matched += 1
                    company_matched += 1
                    logger.info("  🎯 MATCH: %s at %s (%.0f%%)", actual_title, actual_company, result.confidence * 100)

                    if send_telegram(
                        actual_title, actual_company, href, result.reason,
                        source_label=f"Career Page — {company}",
                    ):
                        total_notified += 1
                        logger.info("  ✅ Notified: %s at %s", actual_title, actual_company)
                    else:
                        logger.warning("  ⚠ Telegram failed for %s at %s", actual_title, actual_company)

            if company_jobs > 0:
                logger.info("✅ %s: %d jobs scraped, %d matched, %d notified (%s)",
                            company, company_jobs, company_matched,
                            company_matched, url)
                found = True
                save_seen_jobs(seen_jobs)  # Persist after each company
                break  # Found jobs for this company, skip other ATS patterns

        if not found:
            logger.debug("  ⚠ %s — no career page found", company)

    logger.info("=" * 50)
    logger.info("DONE: %d companies checked, %d jobs, %d matched, %d notified",
                len(companies_to_check), total_jobs, total_matched, total_notified)
    save_seen_jobs(seen_jobs)


if __name__ == "__main__":
    print("🏢 Career Pages Job Tracker (on-the-fly)")
    main()
