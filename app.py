import os
import json
import re
from datetime import datetime, timedelta
import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from ai import match_job, PROFILE

load_dotenv()

# File paths
SEEN_JOBS_FILE = "seen_jobs.json"
ALERTS_FILE = "job_alerts.json"
CLEANUP_META_FILE = "cleanup_meta.json"
CLEANUP_DAYS = 10  # Clear data every 10 days

# Load/save JSON files
def load_json(path, default=None):
    """Load JSON file, return default if file doesn't exist"""
    try:
        with open(path) as f:
            return json.load(f)
    except:
        return default if default is not None else []

def save_json(path, data):
    """Save data to JSON file"""
    with open(path, "w") as f:
        json.dump(data, f)

# Cleanup: Reset all data every 10 days
def check_and_cleanup():
    """Check if 10 days passed and clear all data if needed"""
    now = datetime.utcnow()
    
    # Load last cleanup time
    meta = load_json(CLEANUP_META_FILE, default={})
    last_cleanup = meta.get("last_cleanup")
    
    # If no cleanup record, create one
    if not last_cleanup:
        save_json(CLEANUP_META_FILE, {"last_cleanup": now.isoformat()})
        return
    
    # Check if 10 days passed
    last_dt = datetime.fromisoformat(last_cleanup)
    if now - last_dt >= timedelta(days=CLEANUP_DAYS):
        # Clear everything
        save_json(SEEN_JOBS_FILE, [])
        save_json(ALERTS_FILE, [])
        save_json(CLEANUP_META_FILE, {"last_cleanup": now.isoformat()})
        print("🧹 Cleanup: All data cleared (10 days passed)\n")

def send_telegram(msg):
    """Send message to Telegram"""
    try:
        token = os.getenv("TELEGRAM_TOKEN")
        chat_id = os.getenv("TELEGRAM_CHAT_ID")
        requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": msg},
            timeout=5
        )
    except:
        pass

def scrape_jobs(url, keywords, target_companies):
    """Scrape LinkedIn jobs from URL and filter by keywords"""
    # Get webpage
    try:
        resp = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
        soup = BeautifulSoup(resp.text, "html.parser")
    except:
        return []
    
    jobs = []
    
    # Loop through each job card
    for card in soup.find_all("div", class_="base-card"):
        # Skip promoted jobs
        if card.find("span", class_="result-benefits__text"):
            continue
        
        # Skip jobs with over 100 applicants
        text = card.get_text().lower()
        if "over" in text and ("applicant" in text or "people clicked" in text):
            continue
        
        # Extract job details
        title_tag = card.find("h3", class_="base-search-card__title")
        company_tag = card.find("h4", class_="base-search-card__subtitle")
        link_tag = card.find("a", class_="base-card__full-link")
        
        if not title_tag or not link_tag:
            continue
        
        title = title_tag.get_text(strip=True)
        company = company_tag.get_text(strip=True) if company_tag else ""
        
        # Check if company is in target list
        if not any(tc.lower() in company.lower() for tc in target_companies):
            continue
        
        # Check if job matches using AI (60% confidence minimum)
        match, confidence, _ = match_job(title, company, keywords, target_companies)
        if match and confidence >= 0.6:
            # Extract job ID from URL
            job_id = re.search(r'-(\d+)(?:\?|$)', link_tag.get("href", ""))
            if job_id:
                job_url = f"https://www.linkedin.com/jobs/view/{job_id.group(1)}"
                jobs.append({"title": title, "company": company, "url": job_url})
    
    return jobs

def main():
    """Main job tracker logic"""
    # Step 1: Check if cleanup needed
    check_and_cleanup()
    
    # Step 2: Load saved data
    config = load_json("config.json")
    seen_urls = set(load_json(SEEN_JOBS_FILE))
    alerts = load_json(ALERTS_FILE)
    
    print(f"Job Tracker ({PROFILE['role']})\n")
    
    total_found = 0
    new_alerts = 0
    
    # Step 3: Search each company's career page
    for search in config["companies"]:
        print(f"Searching: {search['name']}")
        
        jobs = scrape_jobs(
            search["career_page"],
            search["keywords"],
            config["target_companies"]
        )
        
        print(f"  Found {len(jobs)} matching jobs")
        total_found += len(jobs)
        
        # Step 4: Send alerts for new jobs
        for job in jobs:
            if job["url"] not in seen_urls:
                new_alerts += 1
                seen_urls.add(job["url"])
                
                # Send to Telegram
                msg = f"New Job: {job['title']}\nCompany: {job['company']}\n{job['url']}"
                send_telegram(msg)
                
                # Save alert
                alerts.append({
                    "title": job["title"],
                    "company": job["company"],
                    "url": job["url"],
                    "sent_at": datetime.utcnow().isoformat()
                })
                
                print(f"  ✅ NEW: {job['title']} at {job['company']}")
        
        print()
    
    # Step 5: Save updated data
    save_json(SEEN_JOBS_FILE, list(seen_urls))
    save_json(ALERTS_FILE, alerts)
    
    print(f"Done. {total_found} jobs found, {new_alerts} new alerts sent.")

if __name__ == "__main__":
    main()