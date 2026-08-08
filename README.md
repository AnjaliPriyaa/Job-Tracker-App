# Agentic Job Tracker

An **autonomous AI agent** that searches for DevOps, Cloud, SRE, and Platform Engineering jobs across multiple sources, evaluates them against your criteria, and notifies you via Telegram.

## What Makes This Agentic?

The **LLM agent decides what to do** — there is no hard-coded workflow. The agent:
- Chooses which search tools to use based on what it discovers
- Investigates uncertain jobs instead of blindly accepting/rejecting
- Recovers from tool failures by trying alternative approaches
- Decides when enough jobs have been found
- Adapts its strategy dynamically

The system provides **tools** (search, discover, fetch, evaluate, notify) and the agent uses them autonomously. Deterministic logic is limited to **policy enforcement** (security, rate limiting, dedup) — never workflow orchestration.

## Architecture

```
agent.py (DeepAgents)
  ├── tools/search_tools.py      — search_linkedin, search_ats, search_web_jobs
  ├── tools/discovery_tools.py   — discover_company_career_page, discover_ats_platform
  ├── tools/job_tools.py         — fetch_job, extract_job_details
  ├── tools/evaluation_tools.py  — evaluate_job (AI matching)
  ├── tools/state_tools.py       — save_job, get_seen_jobs, get_user_preferences
  ├── tools/notification_tools.py — notify_user (→ PolicyEngine → Telegram)
  │
  ├── models/                    — Pydantic schemas (Job, SearchResult, EvaluationResult)
  ├── storage/                   — SQLite (jobs, decisions, notifications, agent_runs)
  ├── policies/                  — PolicyEngine (deterministic validation)
  └── agent/                     — prompts.py, middleware.py (budget enforcement)
```

## How It Works

1. **Agent gets preferences** via `get_user_preferences`
2. **Agent searches** — chooses LinkedIn, ATS pages, or web search
3. **Agent inspects** promising jobs with `fetch_job`
4. **Agent evaluates** using `evaluate_job` (match / reject / investigate)
5. **Agent investigates** uncertain jobs — deeper lookup, skill extraction
6. **Agent notifies** via `notify_user` — PolicyEngine validates before Telegram
7. **Agent stops** when it has sufficient matches or budget is exhausted

## Quick Setup

```bash
pip install -r requirements.txt
cp .env.example .env
# Edit .env: DEEPSEEK_API_KEY, TELEGRAM_TOKEN, TELEGRAM_CHAT_ID
python agent.py
```

## Configuration

Edit `config.json`:
- `target_companies` — companies to monitor
- `roles` — target job roles
- `experience_years` / `min_experience_years`
- `confidence_threshold`
- `exclude_roles`, `exclude_levels`, `exclude_keywords`

## Environment Variables

| Variable | Description |
|---|---|
| `DEEPSEEK_API_KEY` | DeepSeek API key (free tier) |
| `TELEGRAM_TOKEN` | Telegram bot token |
| `TELEGRAM_CHAT_ID` | Your chat ID |

## Policy Layer (Deterministic)

The `PolicyEngine` enforces rules that the AI cannot bypass:
- Target company verification
- Duplicate notification prevention
- Excluded role/level filtering
- Daily notification rate limiting
- Location validation (India only)

## Execution Budgets

Physically enforced limits prevent runaway agents:
- 80 max tool calls
- 8 max searches
- 15 max notifications
- 10 minute timeout

## GitHub Actions

Two independent schedules invoke the **same `agent.py`** with different run contexts. Schedules encode only *when* and *initial focus* — the agent decides the actual workflow.

| Workflow | Schedule | Context |
|---|---|---|
| `linkedin-run.yml` | Every 2 hours | LinkedIn-focused initial search |
| `career-run.yml` | Daily 10 AM IST (4:30 UTC) | Career page discovery + ATS search |

Both share the same SQLite state, tools, policies, and budget infrastructure.

```yaml
# linkedin-run.yml
env:
  RUN_CONTEXT: linkedin

# career-run.yml  
env:
  RUN_CONTEXT: career
```

## Testing

```bash
# Policy tests
python -m pytest tests/test_policy.py -v

# Agenticity tests  
python -m pytest tests/test_agenticity.py -v
```
