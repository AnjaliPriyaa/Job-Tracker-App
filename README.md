# Job Tracker

Auto-scrape LinkedIn for DevOps jobs and get Telegram alerts.

## What it does

- Searches LinkedIn every 20 minutes
- Finds DevOps/SRE jobs at 40 target companies in Bengaluru
- Uses AI to filter jobs (3-6 years experience only)
- Sends new jobs to Telegram
- Clears old data every 10 days

## Setup

1. Add GitHub secrets:
   - TELEGRAM_TOKEN
   - TELEGRAM_CHAT_ID  
   - GEMINI_API_KEY

2. Edit `ai.py` with your role and skills

3. Update `config.json` with companies you want

That's it. GitHub Actions runs it automatically.

## Config

**Profile** (ai.py):
```python
PROFILE = {
    "role": "Senior DevOps Engineer",
    "experience_years": 5,
    "skills": "Python, Docker, Kubernetes, AWS, Azure, Terraform"
}
```

**Search filters** (config.json URL):
- Last 15 hours only 
- 3-6 years experience 
- 40 target companies
- 19 keywords

## How it works

LinkedIn → AI filter (60% match) → Telegram → Save to seen_jobs.json

Every 10 days: auto-cleanup all data

## Files

- app.py (130 lines) - scraper
- ai.py (35 lines) - AI matching
- config.json - companies/keywords
- .github/workflows/job-tracker.yml - runs every 20 min
