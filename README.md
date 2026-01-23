# Job Tracker - GitHub Actions Setup

## Setup Instructions

### 1. Push to GitHub
```bash
git init
git add .
git commit -m "Initial commit"
git remote add origin https://github.com/YOUR_USERNAME/CompanyTracking.git
git push -u origin main
```

### 2. Add GitHub Secrets
Go to your repository → Settings → Secrets and variables → Actions → New repository secret

Add these two secrets:
- `TELEGRAM_TOKEN` = `8453820857:AAFdr0KHiCe5P79eL9pf_4dQrV8v9xTGEJM`
- `TELEGRAM_CHAT_ID` = `5919083312`

### 3. Enable GitHub Actions
- Go to Actions tab in your repository
- Enable workflows if prompted

### 4. Manual Test (Optional)
- Go to Actions → Job Tracker → Run workflow
- Click "Run workflow" to test manually

## How It Works

- Runs every 10 minutes automatically
- Fetches DevOps jobs from LinkedIn (Bengaluru, 0-5 years experience, last 10 hours)
- Filters by 33 target companies
- Sends Telegram alerts for new matches
- Commits `seen_jobs.json` back to prevent duplicates

## Local Testing
```bash
python app.py
```
