# Job Tracker

AI-powered job tracker that monitors LinkedIn and notifies you about relevant opportunities via Telegram.

## Features

- **AI-powered filtering** using Google Gemini (via LangChain)
- **Telegram notifications** for job matches
- **Smart filtering** by experience, roles, keywords, and companies
- **Auto cleanup** every 10 days (clears seen-jobs history)
- **Deterministic pipeline** — reliable, predictable execution

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
   - Set your experience range (`experience_years` / `min_experience_years`)
   - Add target companies
   - List desired roles
   - Add exclude keywords, roles, and levels

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

| Field | Description |
|---|---|
| `experience_years` | Maximum years of experience (e.g., `6`) |
| `min_experience_years` | Minimum years (e.g., `4`) |
| `target_companies` | Companies to monitor |
| `roles` | Job titles you're looking for |
| `exclude_roles` | Roles to skip (`manager`, `lead`, `principal`, etc.) |
| `exclude_levels` | Levels to skip (`junior`, `intern`, etc.) |
| `exclude_keywords` | Keywords to avoid (`frontend`, `blockchain`, etc.) |
| `job_portals` | LinkedIn search URLs with keywords |

## Files

| File | Purpose |
|---|---|
| `agent_app_simple.py` | Main application — `AgenticJobTracker` class + CLI entry point |
| `langchain_ai.py` | AI job matching with Google Gemini (structured output) |
| `langchain_tools.py` | LangChain-compatible tools (scraping, Telegram, filtering) |
| `utils.py` | Shared utilities (JSON I/O, cleanup, seen-jobs tracking) |
| `config.json` | Your configuration |
| `test.py` | End-to-end test suite |

## How It Works

```
Load Config → Scrape Jobs → Pre-filter (exclude rules)
→ AI Match (Gemini) → Send Notification → Track Seen Jobs
```

The pipeline is **deterministic** — the AI is used only for the matching step,
not for orchestrating the workflow. This makes the system reliable and predictable.

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

Made with LangChain, Google Gemini, and Python
