import os
import json
import re
import requests
from bs4 import BeautifulSoup

def load_config():
    with open("config.json") as f:
        config = json.load(f)
    config["telegram_token"] = os.getenv("TELEGRAM_TOKEN", config.get("telegram_token"))
    config["telegram_chat_id"] = os.getenv("TELEGRAM_CHAT_ID", config.get("telegram_chat_id"))
    return config

def load_seen():
    if os.path.exists("seen_jobs.json"):
        with open("seen_jobs.json") as f:
            return set(json.load(f))
    return set()

def save_seen(jobs):
    with open("seen_jobs.json", "w") as f:
        json.dump(list(jobs), f)

def send_telegram(token, chat, msg):
    try:
        requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            data={"chat_id": chat, "text": msg},
            timeout=5
        )
    except:
        pass

def fetch_page(url):
    try:
        r = requests.get(url, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        }, timeout=10)
        r.raise_for_status()
        return r.text
    except:
        return None

def parse_linkedin(html, keywords, companies):
    soup = BeautifulSoup(html, "html.parser")
    jobs = []
    
    for card in soup.find_all("div", class_="base-card"):
        if card.find("span", class_="result-benefits__text"):
            continue
        if card.find(string=re.compile(r"Promoted", re.I)):
            continue
            
        title_elem = card.find("h3", class_="base-search-card__title")
        link_elem = card.find("a", class_="base-card__full-link")
        company_elem = card.find("h4", class_="base-search-card__subtitle")
        
        if not (title_elem and link_elem):
            continue
            
        title = title_elem.get_text(strip=True)
        company = company_elem.get_text(strip=True) if company_elem else ""
        
        if not any(k.lower() in title.lower() for k in keywords):
            continue
        
        if companies and not any(c.lower() in company.lower() for c in companies):
            continue
        
        job_id = re.search(r'-(\d+)(?:\?|$)', link_elem.get("href", ""))
        if job_id:
            url = f"https://www.linkedin.com/jobs/view/{job_id.group(1)}"
            jobs.append((title, url, company))
    
    return jobs

def main():
    print("Starting job check...")
    config = load_config()
    seen = load_seen()
    new_seen = set(seen)
    targets = config.get("target_companies", [])
    
    for source in config["companies"]:
        html = fetch_page(source["career_page"])
        if not html:
            continue
        
        jobs = parse_linkedin(html, source["keywords"], targets)
        print(f"Found {len(jobs)} jobs")
        
        for title, link, company in jobs:
            if link not in seen:
                print(f"New: {title} @ {company}")
                msg = f"🎯 {title}\n\nCompany: {company}\n\n🔗 {link}"
                send_telegram(config["telegram_token"], config["telegram_chat_id"], msg)
                new_seen.add(link)
    
    save_seen(new_seen)
    print("Done")
    print(f"\n✅ Job check completed! Total seen jobs: {len(new_seen_jobs)}")

if __name__ == "__main__":
    main()
