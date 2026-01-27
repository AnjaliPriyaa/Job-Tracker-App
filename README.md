# Job Tracker

Automatically checks LinkedIn for DevOps jobs and sends alerts to Telegram when new positions are posted.

## What it does

Scrapes LinkedIn job listings for DevOps/SRE roles at target companies in Bengaluru. Uses AI to check if jobs match your profile, then sends new matches to Telegram.

## How it works

- Runs every 20 minutes via GitHub Actions
- Scrapes LinkedIn for jobs matching keywords (devops, sre, platform engineer, etc)
- Filters by target companies (Adobe, Microsoft, Flipkart, etc)
- Uses Google Gemini AI to check if job matches your profile and experience level
- Sends new jobs to Telegram
- Keeps track of already-seen jobs to avoid duplicates

## Setup

1. Add secrets to GitHub repo settings (TELEGRAM_TOKEN, TELEGRAM_CHAT_ID, GEMINI_API_KEY)

2. Update `config.json` with your target companies and keywords

3. Edit `ai.py` to set your role, experience, and skills

## Tech

- Python with requests and BeautifulSoup for scraping
- Google Gemini for AI job matching
- Telegram for notifications
- GitHub Actions for scheduling

## Latest Changes (v2)

- Added AI-powered job matching using Gemini
- Simplified code and output
- Better filtering for senior roles (no junior, no manager/director)
- Cleaner console output
- AI falls back to keyword matching if API fails
