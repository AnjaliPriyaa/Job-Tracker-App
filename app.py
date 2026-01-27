import os
import json
import re
import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from ai import match_job, PROFILE

load_dotenv()

def load_config():
    with open("config.json") as f:
        return json.load(f)

def load_seen():
    try:
        with open("seen_jobs.json") as f:
            return set(json.load(f))
    except:
        return set()

def save_seen(jobs):
    with open("seen_jobs.json", "w") as f:
        json.dump(list(jobs), f)

def send_telegram(msg):
    try:
        token = os.getenv("TELEGRAM_TOKEN")
        chat_id = os.getenv("TELEGRAM_CHAT_ID")
        requests.post(f"https://api.telegram.org/bot{token}/sendMessage",
                     json={"chat_id": chat_id, "text": msg}, timeout=5)
    except:
        pass

def parse_jobs(url, keywords, target_companies):
    try:
        resp = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
        soup = BeautifulSoup(resp.text, "html.parser")
    except:
        return [], []
    
    jobs = []
    
    for card in soup.find_all("div", class_="base-card"):
        if card.find("span", class_="result-benefits__text"):
            continue
        
        full_text = card.get_text()
        
        # only jobs with under 100 applicants
        if "over" in full_text.lower() and ("applicant" in full_text.lower() or "people clicked" in full_text.lower()):
            continue
        
        title_tag = card.find("h3", class_="base-search-card__title")
        company_tag = card.find("h4", class_="base-search-card__subtitle")
        link_tag = card.find("a", class_="base-card__full-link")
        
        if not title_tag or not link_tag:
            continue
        
        title = title_tag.get_text(strip=True)
        company = company_tag.get_text(strip=True) if company_tag else ""
        
        # check if target company
        is_target = any(tc.lower() in company.lower() for tc in target_companies)
        if not is_target:
            continue
        
        # check with AI
        match, confidence, _ = match_job(title, company, keywords, target_companies)
        if match and confidence >= 0.6:
            job_id = re.search(r'-(\d+)(?:\?|$)', link_tag.get("href", ""))
            if job_id:
                job_url = f"https://www.linkedin.com/jobs/view/{job_id.group(1)}"
                jobs.append((title, company, job_url))
    
    return jobs, []

def main():
    config = load_config()
    seen = load_seen()
    
    print(f"Job Tracker ({PROFILE['role']})\n")
    
    matched_count = 0
    new_jobs = 0
    
    for search in config["companies"]:
        print(f"Searching: {search['name']}")
        matches, rejects = parse_jobs(search["career_page"], search["keywords"], config["target_companies"])
        
        print(f"  Found {len(matches)} jobs")
        matched_count += len(matches)
        
        for title, company, url in matches:
            if url not in seen:
                new_jobs += 1
                seen.add(url)
                msg = f"New Job: {title}\nCompany: {company}\n{url}"
                send_telegram(msg)
                print(f"  NEW: {title} at {company}")
        print()
    
    save_seen(seen)
    print(f"Done. {matched_count} jobs found, {new_jobs} new alerts sent.")

if __name__ == "__main__":
    main()