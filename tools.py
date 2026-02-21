from langchain_core.tools import tool
import json
import os
import requests
import re
from bs4 import BeautifulSoup
from datetime import datetime, UTC

SEEN_JOBS_FILE = "seen_jobs.json"


# -----------------------------
# CONFIG
# -----------------------------
@tool
def load_config(_: str = "") -> str:
    """Load job search configuration"""
    with open("config.json") as f:
        return json.dumps(json.load(f))


# -----------------------------
# SEEN JOBS
# -----------------------------
@tool
def manage_seen_jobs(input_data: str) -> str:
    """
    Manage seen jobs.
    Input JSON: {action: "check"|"add", job_id: str}
    """
    data = json.loads(input_data)

    if os.path.exists(SEEN_JOBS_FILE):
        with open(SEEN_JOBS_FILE) as f:
            seen = set(json.load(f))
    else:
        seen = set()

    if data["action"] == "check":
        return json.dumps({"seen": data["job_id"] in seen})

    elif data["action"] == "add":
        seen.add(data["job_id"])
        with open(SEEN_JOBS_FILE, "w") as f:
            json.dump(list(seen), f)
        return json.dumps({"status": "added"})


# -----------------------------
# SCRAPE JOBS
# -----------------------------
@tool
def scrape_jobs(input_data: str) -> str:
    """
    Scrape jobs from LinkedIn.
    Input JSON: {url: str, target_companies: list}
    """
    data = json.loads(input_data)

    try:
        resp = requests.get(
            data["url"],
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=10
        )
        soup = BeautifulSoup(resp.text, "html.parser")
    except Exception as e:
        return json.dumps({"error": str(e), "jobs": []})

    jobs = []

    for card in soup.find_all("div", class_="base-card"):
        title = card.find("h3")
        company = card.find("h4")
        link = card.find("a")

        if not title or not company or not link:
            continue

        title = title.get_text(strip=True)
        company = company.get_text(strip=True)

        if not any(tc.lower() in company.lower() for tc in data["target_companies"]):
            continue

        job_id_match = re.search(r'-(\d+)', link.get("href", ""))
        if not job_id_match:
            continue

        job_id = job_id_match.group(1)
        job_url = f"https://www.linkedin.com/jobs/view/{job_id}"

        jobs.append({
            "id": job_id,
            "title": title,
            "company": company,
            "url": job_url
        })

    return json.dumps({"jobs": jobs})


# -----------------------------
# JOB DESCRIPTION
# -----------------------------
@tool
def get_job_description(job_url: str) -> str:
    """Fetch job description from URL"""
    try:
        resp = requests.get(job_url, headers={"User-Agent": "Mozilla/5.0"})
        soup = BeautifulSoup(resp.text, "html.parser")

        desc = soup.find("div", class_="show-more-less-html__markup")

        if not desc:
            return ""

        return desc.get_text(separator="\n", strip=True)[:2000]

    except Exception as e:
        return f"ERROR: {str(e)}"


# -----------------------------
# TELEGRAM
# -----------------------------
@tool
def send_telegram(message: str) -> str:
    """Send Telegram message"""
    token = os.getenv("TELEGRAM_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")

    if not token or not chat_id:
        return "Telegram not configured"

    requests.post(
        f"https://api.telegram.org/bot{token}/sendMessage",
        json={"chat_id": chat_id, "text": message}
    )

    return "sent"