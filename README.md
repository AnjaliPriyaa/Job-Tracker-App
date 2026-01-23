# Job Tracker - GitHub Actions Setup



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
