import os
import json
import re
import requests
from bs4 import BeautifulSoup

def load_config():
    with open("config.json", "r") as f:
        config = json.load(f)
    # Override with environment variables if available
    config["telegram_token"] = os.environ.get("TELEGRAM_TOKEN", config.get("telegram_token"))
    config["telegram_chat_id"] = os.environ.get("TELEGRAM_CHAT_ID", config.get("telegram_chat_id"))
    return config

def load_seen_jobs():
    if os.path.exists("seen_jobs.json"):
        with open("seen_jobs.json", "r") as f:
            return set(json.load(f))
    return set()

def save_seen_jobs(seen_jobs):
    with open("seen_jobs.json", "w") as f:
        json.dump(list(seen_jobs), f)

def send_telegram_message(token, chat_id, message):
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    data = {"chat_id": chat_id, "text": message}
    try:
        requests.post(url, data=data, timeout=5)
    except Exception as e:
        print(f"Failed to send Telegram message: {e}")

def fetch_jobs(url, is_linkedin=False):
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
    }
    try:
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        return response.text
    except Exception as e:
        print(f"Failed to fetch {url}: {e}")
        return None

def parse_jobs(html, keywords, is_linkedin=False, target_companies=None):
    soup = BeautifulSoup(html, "html.parser")
    jobs = []
    
    if is_linkedin:
        job_cards = soup.find_all("div", class_="base-card")
        for card in job_cards:
            # Skip promoted jobs
            if card.find("span", class_="result-benefits__text") or card.find(string=re.compile(r"Promoted", re.IGNORECASE)):
                continue
                
            title_elem = card.find("h3", class_="base-search-card__title")
            job_id_elem = card.find("a", class_="base-card__full-link")
            company_elem = card.find("h4", class_="base-search-card__subtitle")
            
            if not (title_elem and job_id_elem):
                continue
                
            title = title_elem.get_text(strip=True)
            company_name = company_elem.get_text(strip=True) if company_elem else ""
            
            if not any(kw.lower() in title.lower() for kw in keywords):
                continue
            
            if target_companies and not any(c.lower() in company_name.lower() for c in target_companies):
                continue
            
            match = re.search(r'-(\d+)(?:\?|$)', job_id_elem.get("href", ""))
            if match:
                job_id = match.group(1)
                job_url = f"https://www.linkedin.com/jobs/view/{job_id}"
                jobs.append((title, job_url, company_name))
    
    return jobs

def main():
    config = load_config()
    seen_jobs = load_seen_jobs()
    new_seen_jobs = set(seen_jobs)
    target_companies = config.get("target_companies", [])

    for company in config["companies"]:
        html = fetch_jobs(company["career_page"], company.get("is_linkedin", False))
        if not html:
            continue

        jobs = parse_jobs(html, company["keywords"], company.get("is_linkedin", False), target_companies)
        
        for title, link, company_name in jobs:
            if link not in seen_jobs:
                message = f"🎯 New Job Opening\n\n{title}\n\nCompany: {company_name}\n\n📍 {company['name']}\n\n🔗 {link}"
                send_telegram_message(config["telegram_token"], config["telegram_chat_id"], message)
                new_seen_jobs.add(link)

    save_seen_jobs(new_seen_jobs)

if __name__ == "__main__":
    main()
