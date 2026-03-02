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

    # LinkedIn's job search results use specific class names for job cards.
    # 'job-search-card' is a common class for the container of each job listing.
    # We also check for 'base-card' as a fallback.
    job_cards = soup.find_all("div", class_=["job-search-card", "base-card"])

    if not job_cards:
        # If no cards are found, it's possible the page layout has changed or
        # we were blocked. A more descriptive error is helpful.
        return json.dumps({
            "error": "Could not find any job cards on the page. LinkedIn may have blocked the request or changed its page layout.",
            "jobs": []
        })

    for card in job_cards:
        # Using more specific selectors to reliably get the right information.
        title_el = card.find("h3", class_="base-search-card__title")
        company_el = card.find("h4", class_="base-search-card__subtitle")
        link_el = card.find("a", class_="base-card__full-link")

        # Fallback to less specific tags if the primary ones aren't found.
        if not link_el:
            link_el = card.find("a")
        if not title_el:
            title_el = card.find("h3")
        if not company_el:
            company_el = card.find("h4")

        if not title_el or not company_el or not link_el:
            continue

        title = title_el.get_text(strip=True)
        company = company_el.get_text(strip=True)
        link_href = link_el.get("href", "")

        # Only filter by company if the list is not empty.
        if data.get("target_companies") and not any(tc.lower() in company.lower() for tc in data["target_companies"]):
            continue

        # Handle different URL formats for extracting job ID.
        job_id_match = re.search(r'currentJobId=(\d+)', link_href) or re.search(r'-(\d+)', link_href)
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
        resp = requests.get(job_url, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
        soup = BeautifulSoup(resp.text, "html.parser")

        # The 'jobs-description' class usually contains the entire description section,
        # including the main text, responsibilities, and qualifications.
        # This is a more comprehensive container than 'show-more-less-html__markup'.
        desc_container = soup.find("div", class_="jobs-description")

        if desc_container:
            # Getting text from this container should include all relevant details.
            # We use separator='\n' to maintain line breaks for readability.
            full_description = desc_container.get_text(separator="\n", strip=True)
            return full_description[:4000] # Increased limit for more detail

        # Fallback to the original method if 'jobs-description' is not found
        desc_el = soup.find("div", class_="show-more-less-html__markup")
        if desc_el:
            return desc_el.get_text(separator="\n", strip=True)[:4000]

        return "ERROR: Could not find job description container. The page layout may have changed."

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


# -----------------------------
# FILTER JOBS
# -----------------------------
@tool
def filter_jobs_by_experience(input_data: str) -> str:
    """
    Filter jobs based on experience level.
    Input JSON: {jobs: list, my_experience: float (years)}
    """
    data = json.loads(input_data)
    my_experience = data["my_experience"]
    
    filtered_jobs = []
    
    for job in data["jobs"]:
        title = job.get("title", "").lower()
        desc = job.get("description", "").lower() # Assuming description is fetched and added to job dict
        
        # Check for junior level keywords
        if any(keyword in title for keyword in ["junior", "entry-level", "graduate"]):
            filtered_jobs.append(job)
            continue
            
        # Check for year ranges using regex
        # This regex looks for patterns like "3-5 years", "3+ years", "5 years of experience"
        # and captures the numbers.
        exp_range_match = re.search(r'(\d+)\s*-\s*(\d+)\s*years', desc)
        exp_plus_match = re.search(r'(\d+)\+\s*years', desc)
        exp_single_match = re.search(r'(\d+)\s*years', desc)
        
        min_exp = 0
        max_exp = float('inf')
        
        if exp_range_match:
            min_exp = int(exp_range_match.group(1))
            max_exp = int(exp_range_match.group(2))
        elif exp_plus_match:
            min_exp = int(exp_plus_match.group(1))
        elif exp_single_match:
            min_exp = int(exp_single_match.group(1))
            # If it's a single number, we can assume a small range around it
            max_exp = min_exp + 2

        # Check if user's experience is a good fit.
        # We add a 1.5 year flexibility, so if a job requires 5 years,
        # a person with 3.5+ years is still considered a potential match.
        # We don't check for an upper bound, as being overqualified is not a reason to filter out.
        if min_exp <= my_experience + 1.5:
            filtered_jobs.append(job)
            
    return json.dumps({"filtered_jobs": filtered_jobs})