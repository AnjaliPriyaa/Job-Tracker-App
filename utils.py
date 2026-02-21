"""Shared utility functions for job tracking"""
import json
import os
import re
import requests
from bs4 import BeautifulSoup
from datetime import datetime, UTC


SEEN_JOBS_FILE = "seen_jobs.json"
CLEANUP_META_FILE = "cleanup_meta.json"
CLEANUP_DAYS = 10


def load_config(path: str = "config.json") -> dict:
    """Load configuration file"""
    with open(path) as f:
        return json.load(f)


def load_seen_jobs() -> set:
    """Load list of previously seen jobs"""
    if os.path.exists(SEEN_JOBS_FILE):
        with open(SEEN_JOBS_FILE) as f:
            return set(json.load(f))
    return set()


def save_seen_jobs(seen_jobs: set):
    """Save list of seen jobs"""
    with open(SEEN_JOBS_FILE, "w") as f:
        json.dump(list(seen_jobs), f)


def check_and_cleanup():
    """Check if cleanup is needed and perform it"""
    now = datetime.now(UTC)
    
    if os.path.exists(CLEANUP_META_FILE):
        with open(CLEANUP_META_FILE) as f:
            meta = json.load(f)
        last = meta.get("last_cleanup")
    else:
        last = None
    
    if not last:
        with open(CLEANUP_META_FILE, "w") as f:
            json.dump({"last_cleanup": now.isoformat()}, f)
        print("🔧 Initialized cleanup tracking\n")
        return
    
    last_dt = datetime.fromisoformat(last)
    if last_dt.tzinfo is None:
        last_dt = last_dt.replace(tzinfo=UTC)
    
    days_since = (now - last_dt).days
    
    if days_since >= CLEANUP_DAYS:
        with open(SEEN_JOBS_FILE, "w") as f:
            json.dump([], f)
        with open(CLEANUP_META_FILE, "w") as f:
            json.dump({"last_cleanup": now.isoformat()}, f)
        print(f"🧹 Cleanup performed (after {days_since} days)\n")
    else:
        print(f"✓ No cleanup needed ({days_since}/{CLEANUP_DAYS} days)\n")


def scrape_jobs(url: str, target_companies: list) -> list:
    """Scrape jobs from LinkedIn"""
    try:
        resp = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
        soup = BeautifulSoup(resp.text, "html.parser")
    except Exception as e:
        print(f"❌ Failed to scrape jobs: {e}")
        return []
    
    jobs = []
    for card in soup.find_all("div", class_="base-card"):
        title_tag = card.find("h3", class_="base-search-card__title")
        company_tag = card.find("h4", class_="base-search-card__subtitle")
        link_tag = card.find("a", class_="base-card__full-link")
        
        if not title_tag or not link_tag or not company_tag:
            continue
        
        title = title_tag.get_text(strip=True)
        company = company_tag.get_text(strip=True)
        
        # Filter by target company
        if not any(tc.lower() in company.lower() for tc in target_companies):
            continue
        
        # Extract job URL
        job_id = re.search(r'-(\d+)(?:\?|$)', link_tag.get("href", ""))
        if not job_id:
            continue
        
        job_url = f"https://www.linkedin.com/jobs/view/{job_id.group(1)}"
        
        jobs.append({
            "title": title,
            "company": company,
            "url": job_url
        })
    
    return jobs


def get_job_description(job_url: str) -> str:
    """Fetch full job description"""
    try:
        resp = requests.get(job_url, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
        soup = BeautifulSoup(resp.text, "html.parser")
        
        desc_div = (
            soup.find("div", class_="show-more-less-html__markup") or
            soup.find("div", class_="description__text") or
            soup.find("article", class_="jobs-description__container")
        )
        
        if not desc_div:
            return ""
        
        return desc_div.get_text(separator="\n", strip=True)
    except Exception as e:
        print(f"   ⚠️  Failed to fetch description: {e}")
        return ""


def send_telegram(message: str) -> bool:
    """Send notification via Telegram"""
    try:
        token = os.getenv('TELEGRAM_TOKEN')
        chat_id = os.getenv('TELEGRAM_CHAT_ID')
        
        if not token or not chat_id:
            print("   ⚠️  Telegram credentials not configured")
            return False
        
        response = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": message},
            timeout=5
        )
        return response.status_code == 200
    except Exception as e:
        print(f"   ⚠️  Telegram send failed: {e}")
        return False
