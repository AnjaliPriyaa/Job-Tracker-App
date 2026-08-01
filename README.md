# Job Tracker

AI-powered job tracker that monitors LinkedIn and notifies you about relevant opportunities via Telegram.

## Features

- **AI-powered filtering** using DeepSeek (free tier) or Google Gemini
- **Telegram notifications** for job matches
- **Smart filtering** by experience, roles, keywords, and companies
- **Configurable confidence threshold** for AI matching
- **Retry logic** with exponential backoff for scraping and fetching
- **Auto cleanup** every 10 days (clears seen-jobs history)
- **Deterministic pipeline** — reliable, predictable execution

## Quick Setup

### 1. Get a free AI API key

**Recommended: DeepSeek (free tier)**
1. Sign up at [platform.deepseek.com](https://platform.deepseek.com)
2. Go to API Keys → create a key
3. New users get free credits (no credit card needed initially)

**Alternative: Google Gemini**
1. Get a key at [aistudio.google.com/apikey](https://aistudio.google.com/apikey)
2. Gemini has a free tier with rate limits

### 2. Set up the project

```bash
# Install dependencies
pip install -r requirements.txt

# Copy and edit the env file
cp .env.example .env
# Edit .env — add your DEEPSEEK_API_KEY (or GEMINI_API_KEY)
```

### 3. Configure `config.json`

Edit the fields to match your preferences:
- `experience_years` / `min_experience_years` — your experience range
- `confidence_threshold` — minimum AI confidence to notify (default 0.6)
- `target_companies` — companies to monitor
- `roles` — job titles to match
- `exclude_roles` / `exclude_levels` / `exclude_keywords` — jobs to skip

### 4. Run

```bash
python agent_app_simple.py
```

### 5. Test

```bash
python test.py
```

## Configuration Reference

| Field | Description |
|---|---|
| `experience_years` | Maximum years of experience (e.g., `6`) |
| `min_experience_years` | Minimum years (e.g., `4`) |
| `confidence_threshold` | Minimum AI confidence to send notification (0.0–1.0) |
| `target_companies` | Companies to monitor |
| `roles` | Job titles you're looking for |
| `exclude_roles` | Roles to skip (`manager`, `lead`, `principal`, etc.) |
| `exclude_levels` | Levels to skip (`junior`, `intern`, etc.) |
| `exclude_keywords` | Keywords to avoid (`frontend`, `blockchain`, etc.) |
| `job_portals` | LinkedIn search URLs with keywords |

## Environment Variables

| Variable | Required | Description |
|---|---|---|
| `DEEPSEEK_API_KEY` | Recommended | DeepSeek API key (free tier available) |
| `DEEPSEEK_MODEL` | Optional | Model name (default: `deepseek-chat`) |
| `GEMINI_API_KEY` | Alternative | Google Gemini API key |
| `GEMINI_MODEL` | Optional | Model name (default: `gemini-2.5-flash`) |
| `AI_PROVIDER` | Optional | Force provider: `deepseek` or `gemini` |
| `TELEGRAM_TOKEN` | Yes | Telegram bot token from @BotFather |
| `TELEGRAM_CHAT_ID` | Yes | Your Telegram chat ID |

## Files

| File | Purpose |
|---|---|
| `agent_app_simple.py` | Main application — deterministic pipeline |
| `langchain_ai.py` | AI job matching (DeepSeek & Gemini) |
| `langchain_tools.py` | Tools: scraping, Telegram, filtering |
| `agent.py` | LangGraph ReAct agent (experimental) |
| `utils.py` | Shared utilities (JSON I/O, cleanup) |
| `config.json` | Your job search preferences |
| `.env.example` | Environment variable template |
| `test.py` | End-to-end test suite (10 tests) |

## How It Works

```
Load Config → Scrape Jobs → Pre-filter (exclude rules)
→ AI Match (DeepSeek/Gemini) → Send Telegram → Track Seen Jobs
```

The pipeline is **deterministic** — the AI is used only for the matching step,
not for orchestrating the workflow. This makes the system reliable and predictable.

## GitHub Actions

Run automatically every 2 hours:

```yaml
# .github/workflows/job-tracker.yml
on:
  schedule:
    - cron: '7 */2 * * *'
  workflow_dispatch:
```

Add your API keys as [repository secrets](https://docs.github.com/en/actions/security-guides/encrypted-secrets).

---

Made with LangChain, DeepSeek/Gemini, and Python
