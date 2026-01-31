import os
import json
import re
from datetime import datetime, timedelta, UTC
import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from ai import match_job

load_dotenv()

SEEN_JOBS_FILE = "seen_jobs.json"
CLEANUP_META_FILE = "cleanup_meta.json"
CLEANUP_DAYS = 10

def load_json(path, default=None):
    try:
        with open(path) as f:
            return json.load(f)
    except:
        return default or []

def save_json(path, data):
    with open(path, "w") as f:
        json.dump(data, f)

def check_and_cleanup():
    now = datetime.now(UTC)
    meta = load_json(CLEANUP_META_FILE, default={})
    last = meta.get("last_cleanup")
    
    if not last:
        save_json(CLEANUP_META_FILE, {"last_cleanup": now.isoformat()})
        return
    
    last_dt = datetime.fromisoformat(last)
    if last_dt.tzinfo is None:
        last_dt = last_dt.replace(tzinfo=UTC)
    
    if now - last_dt >= timedelta(days=CLEANUP_DAYS):
        save_json(SEEN_JOBS_FILE, [])
        save_json(CLEANUP_META_FILE, {"last_cleanup": now.isoformat()})
        print("🧹 Cleanup done (10 days)\n")

def send_telegram(msg):
    try:
        requests.post(
            f"https://api.telegram.org/bot{os.getenv('TELEGRAM_TOKEN')}/sendMessage",
            json={"chat_id": os.getenv("TELEGRAM_CHAT_ID"), "text": msg},
            timeout=5
        )
    except:
        pass

def get_job_details(url):
    """Fetch full job description from job page"""
    try:
        resp = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
        soup = BeautifulSoup(resp.text, "html.parser")
        
        # Try multiple selectors for full description
        desc_div = (
            soup.find("div", class_="show-more-less-html__markup") or
            soup.find("div", class_="description__text") or
            soup.find("article", class_="jobs-description__container")
        )
        
        if not desc_div:
            return None
        
        # Get full text with line breaks preserved
        description = desc_div.get_text(separator="\n", strip=True).lower()
        # print(f"\n=== FULL DESCRIPTION ({len(description)} chars) ===")
        # print(description)
        # print("=== END DESCRIPTION ===\n")
        
        return {"description": description}
    except:
        return None

def scrape_jobs(url, keywords, target_companies, exclude_roles, exclude_levels, exclude_keywords, config):
    try:
        resp = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
        soup = BeautifulSoup(resp.text, "html.parser")
    except:
        return []
    
    jobs = []
    for card in soup.find_all("div", class_="base-card"):
        # Get job info
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
        
        # Pre-filter: Check if title contains excluded roles (manager, director, etc.)
        title_lower = title.lower()
        if any(role in title_lower for role in exclude_roles):
            continue
        
        # Pre-filter: Check if title contains excluded levels (junior, intern, etc.)
        if any(level in title_lower for level in exclude_levels):
            continue
        
        # Extract job URL
        job_id = re.search(r'-(\d+)(?:\?|$)', link_tag.get("href", ""))
        if not job_id:
            continue
        
        job_url = f"https://www.linkedin.com/jobs/view/{job_id.group(1)}"
        
        # Get full job details
        details = get_job_details(job_url)
        if not details:
            continue
        
        description = details["description"]
        
        # Log details before AI check
        print(f"\n  Checking: {title} at {company}")
        print(f"  URL: {job_url}")
        print(f"  Description preview: {description[:200]}...")
        print(f"  Excluded keywords check - Junior: {any(role in description for role in exclude_levels)}, Lead: {any(role in description for role in exclude_roles)}")
        
        # AI filter with full description (60% confidence min)
        match, confidence, reason = match_job(title, company, keywords, target_companies, description, exclude_keywords, exclude_roles, exclude_levels, config.get('experience_years', 5))
        print(f"  AI Result: Match={match}, Confidence={confidence}")
        print(f"  Reason: {reason}")
        
        if match and confidence >= 0.6:
            jobs.append({
                "title": title,
                "company": company,
                "url": job_url
            })
    
    return jobs

def main():
    """Main job tracker logic"""
    # Step 1: Check if cleanup needed
    check_and_cleanup()
    
    config = load_json("config.json")
    seen_urls = set(load_json(SEEN_JOBS_FILE))
    
    print(f"Job Tracker ({config['role']})\n")
    
    total, new = 0, 0
    
    for search in config["job_portals"]:
        print(f"Searching: {search['name']}")
        jobs = scrape_jobs(
            search["career_page"], 
            search["keywords"], 
            config["target_companies"],
            config["exclude_roles"],
            config["exclude_levels"],
            config["exclude_keywords"],
            config
        )
        
        print(f"  Found {len(jobs)} jobs")
        total += len(jobs)
        
        for job in jobs:
            if job["url"] not in seen_urls:
                new += 1
                seen_urls.add(job["url"])
                
                msg = f"New Job: {job['title']}\nCompany: {job['company']}\n{job['url']}"
                send_telegram(msg)
                print(f"  NEW: {job['title']} at {job['company']}")

    
    save_json(SEEN_JOBS_FILE, list(seen_urls))
    print(f"Done. {total} jobs, {new} new.")

if __name__ == "__main__":
    main()