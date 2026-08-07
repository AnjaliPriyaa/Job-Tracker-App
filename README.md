# Job Tracker

Agentic AI-powered job tracker that searches **LinkedIn and company career pages**, filters matches using DeepSeek, and notifies you via Telegram.

## Features

- **Two-source search**: LinkedIn job listings + company career pages (Greenhouse/Lever/Ashby)
- **Agentic orchestration** using [LangChain DeepAgents](https://docs.langchain.com/oss/python/deepagents/overview) — the agent plans, searches, and evaluates autonomously
- **AI-powered filtering** using DeepSeek (free tier) or Google Gemini
- **Telegram notifications** with job title, company, link, and match reason
- **Automatic dedup** — tracks seen jobs so you never get the same notification twice
- **Smart filtering** by company, role, keywords, experience, and exclusions
- **Retry logic** with exponential backoff for scraping and fetching
- **Auto cleanup** every 10 days (clears seen-jobs history)

## Quick Setup

### 1. Get a free AI API key

**Recommended: DeepSeek (free tier)**
1. Sign up at [platform.deepseek.com](https://platform.deepseek.com)
2. Go to API Keys → create a key
3. New users get free credits

**Alternative: Google Gemini**
1. Get a key at [aistudio.google.com/apikey](https://aistudio.google.com/apikey)

### 2. Set up Telegram bot

1. Create a bot with [@BotFather](https://t.me/BotFather) → get the token
2. Get your chat ID from [@userinfobot](https://t.me/userinfobot)

### 3. Install and configure

```bash
# Install dependencies
pip install -r requirements.txt

# Copy and edit the env file
cp .env.example .env
# Add: DEEPSEEK_API_KEY, TELEGRAM_TOKEN, TELEGRAM_CHAT_ID
```

### 4. Configure `config.json`

| Field | Description |
|---|---|
| `target_companies` | Companies to monitor (~114 configured) |
| `roles` | Target roles: DevOps, SRE, Cloud, Platform Engineer |
| `experience_years` / `min_experience_years` | Experience range (e.g., 4-6) |
| `confidence_threshold` | Minimum AI confidence to notify (default 0.6) |
| `exclude_roles` | Skip: manager, lead, architect, principal... |
| `exclude_levels` | Skip: junior, intern, entry level... |
| `exclude_keywords` | Skip: frontend, blockchain, 8+ years... |
| `job_portals` | LinkedIn search URL and keywords |

### 5. Run

```bash
# Agentic multi-platform tracker (requires Python 3.11+)
python agentic_tracker.py

# Deterministic LinkedIn-only pipeline (Python 3.9+)
python agent_app_simple.py
```

### 6. Test

```bash
python test.py
```

## Architecture

```
┌──────────────────────────────────────────────────┐
│              create_deep_agent()                  │
│         (LangChain DeepAgents harness)            │
│                                                   │
│  Tools:                                           │
│  ├── search_linkedin     ├── get_job_description  │
│  ├── search_naukri       ├── match_job (DeepSeek) │
│  ├── search_indeed       ├── send_telegram        │
│  ├── search_instahyre    └── manage_seen_jobs     │
│  └── search_career_pages                          │
│                                                   │
│  Middleware:                                      │
│  └── TodoListMiddleware (task planning)           │
└──────────────────────────────────────────────────┘
```

## How It Works

```
1. Agent loads config.json
2. Searches ALL platforms in parallel
3. For each job found:
   → Fetches full description (extracts real company & title from page)
   → Checks company against target list
   → AI evaluates match (role, keywords, experience, exclusions)
   → If match → Telegram notification → marks as seen
4. Persists seen jobs to avoid duplicates
```

## Environment Variables

| Variable | Required | Description |
|---|---|---|
| `DEEPSEEK_API_KEY` | Recommended | DeepSeek API key (free tier) |
| `DEEPSEEK_MODEL` | Optional | Model name (default: `deepseek-chat`) |
| `GEMINI_API_KEY` | Alternative | Google Gemini API key |
| `TELEGRAM_TOKEN` | Yes | Telegram bot token |
| `TELEGRAM_CHAT_ID` | Yes | Your Telegram chat ID |

## Files

| File | Purpose |
|---|---|
| `agentic_tracker.py` | **Agentic multi-platform tracker** (CI entry point) |
| `agent_app_simple.py` | Deterministic LinkedIn-only pipeline (local fallback) |
| `langchain_ai.py` | AI job matching with DeepSeek/Gemini + structured output |
| `langchain_tools.py` | Shared tools: Telegram, description fetch, seen-jobs |
| `tools/scraper_tools.py` | Platform scrapers: LinkedIn, Naukri, Indeed, Instahyre, Career Pages |
| `utils.py` | Shared utilities (JSON I/O, cleanup) |
| `config.json` | Job search preferences and platform URLs |
| `.env.example` | Environment variable template |
| `test.py` | End-to-end test suite |

## GitHub Actions

Runs automatically every 2 hours via `agentic_tracker.py`. Add your API keys as [repository secrets](https://docs.github.com/en/actions/security-guides/encrypted-secrets):
- `DEEPSEEK_API_KEY`
- `TELEGRAM_TOKEN`
- `TELEGRAM_CHAT_ID`

Also supports manual trigger: **Actions → Job Tracker → Run workflow**

---

Made with LangChain DeepAgents, DeepSeek, and Python
