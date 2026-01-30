import os
import json
import re
from datetime import datetime, timedelta
import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from ai import match_job, PROFILE

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
    now = datetime.utcnow()
    meta = load_json(CLEANUP_META_FILE, default={})
    last = meta.get("last_cleanup")
    
    if not last:
        save_json(CLEANUP_META_FILE, {"last_cleanup": now.isoformat()})
        return
    
    if now - datetime.fromisoformat(last) >= timedelta(days=CLEANUP_DAYS):
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

def scrape_jobs(url, keywords, target_companies):
    try:
        resp = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
        soup = BeautifulSoup(resp.text, "html.parser")
    except:
        return []
    
    jobs = []
    for card in soup.find_all("div", class_="base-card"):
        # Skip promoted and popular jobs
        if card.find("span", class_="result-benefits__text"):
            continue
        text = card.get_text().lower()
        if "over" in text and ("applicant" in text or "people clicked" in text):
            continue
        
        # Get job info
        title_tag = card.find("h3", class_="base-search-card__title")
        company_tag = card.find("h4", class_="base-search-card__subtitle")
        link_tag = card.find("a", class_="base-card__full-link")
        
        if not title_tag or not link_tag:
            continue
        
        title = title_tag.get_text(strip=True)
        company = company_tag.get_text(strip=True) if company_tag else ""
        
        # Filter by target company
        if not any(tc.lower() in company.lower() for tc in target_companies):
            continue
        
        # AI filter (60% confidence min)
        match, confidence, _ = match_job(title, company, keywords, target_companies)
        if match and confidence >= 0.6:
            job_id = re.search(r'-(\d+)(?:\?|$)', link_tag.get("href", ""))
            if job_id:
                jobs.append({
                    "title": title,
                    "company": company,
                    "url": f"https://www.linkedin.com/jobs/view/{job_id.group(1)}"
                })
    
    return jobs

def main():
    """Main job tracker logic"""
    # Step 1: Check if cleanup needed
    check_and_cleanup()
    
    config = load_json("config.json")
    seen_urls = set(load_json(SEEN_JOBS_FILE))
    
    print(f"Job Tracker ({PROFILE['role']})\n")
    
    total, new = 0, 0
    
    for search in config["companies"]:
        print(f"Searching: {search['name']}")
        jobs = scrape_jobs(search["career_page"], search["keywords"], config["target_companies"])
        
        print(f"  Found {len(jobs)} jobs")
        total += len(jobs)
        
        for job in jobs:
            if job["url"] not in seen_urls:
                new += 1
                seen_urls.add(job["url"])
                
                msg = f"New Job: {job['title']}\nCompany: {job['company']}\n{job['url']}"
                send_telegram(msg)
                print(f"  ✅ NEW: {job['title']} at {job['company']}")
        print()
    
    save_json(SEEN_JOBS_FILE, list(seen_urls))
    print(f"Done. {total} jobs, {new} new.")

if __name__ == "__main__":
    main()