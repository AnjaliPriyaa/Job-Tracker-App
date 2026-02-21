# Job Tracker 🤖

AI-powered job tracker that monitors LinkedIn and notifies you about relevant opportunities.

## Features

- **AI-powered filtering** using Google Gemini
- **Telegram notifications** for job matches
- **Smart filtering** by experience, roles, and keywords
- **Auto cleanup** every 10 days

## Quick Setup

1. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

2. **Create `.env` file:**
   ```
   GEMINI_API_KEY=your_gemini_api_key
   TELEGRAM_TOKEN=your_telegram_bot_token
   TELEGRAM_CHAT_ID=your_chat_id
   ```

3. **Configure `config.json`:**
   - Set your experience range (min/max years)
   - Add target companies
   - List desired roles
   - Add exclude keywords/roles

4. **Run:**
   ```bash
   python agent_app_simple.py
   ```

5. **Test:**
   ```bash
   python test.py
   ```

## Configuration

Edit `config.json` to customize:

- `experience_years`: Maximum years of experience (e.g., 6)
- `min_experience_years`: Minimum years (e.g., 4)
- `target_companies`: Companies to monitor
- `roles`: Job titles you're looking for
- `exclude_roles`: Roles to skip (manager, lead, principal, etc.)
- `exclude_keywords`: Keywords to avoid (frontend, blockchain, etc.)

## Files

- `agent_app_simple.py` - Main application
- `utils.py` - Shared utilities
- `langchain_ai.py` - AI matching logic
- `langchain_tools.py` - LangChain tools
- `config.json` - Your configuration
- `test.py` - End-to-end test

## How It Works

```
Load Config → Scrape Jobs → Filter (exclude rules) 
→ AI Match → Send Notification → Track Seen Jobs
```

## Troubleshooting

- **No jobs found?** Check your LinkedIn URL and target companies
- **Wrong matches?** Adjust experience range and exclude keywords
- **Setup issues?** Run `python test.py` to verify everything works

## GitHub Actions (Optional)

Run automatically every 20 minutes:

```yaml
# .github/workflows/job-tracker.yml
on:
  schedule:
    - cron: '*/20 * * * *'
jobs:
  track:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - uses: actions/setup-python@v4
      - run: pip install -r requirements.txt
      - run: python agent_app_simple.py
        env:
          GEMINI_API_KEY: ${{ secrets.GEMINI_API_KEY }}
          TELEGRAM_TOKEN: ${{ secrets.TELEGRAM_TOKEN }}
          TELEGRAM_CHAT_ID: ${{ secrets.TELEGRAM_CHAT_ID }}
```

---

Made with ❤️ using LangChain and Google Gemini
