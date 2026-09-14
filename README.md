# Agentic Job Tracker

An **autonomous AI agent** that searches for DevOps, Cloud, SRE, and Platform Engineering jobs across multiple sources, evaluates them against your criteria, and notifies you via Telegram.

## What Makes This Agentic?

The **LLM agent decides what to do** — there is no hard-coded workflow. The agent:
- Chooses which search tools to use based on what it discovers
- Investigates uncertain jobs instead of blindly accepting/rejecting
- Recovers from tool failures by trying alternative approaches
- Decides when enough jobs have been found
- Adapts its strategy dynamically

The system provides **tools** (search, discover, fetch, evaluate, notify) and the agent uses them autonomously. Deterministic logic handles **policy enforcement and obvious job decisions** (security, rate limiting, dedup, hard exclusions, clear matches); it does not orchestrate the workflow.

## Architecture

```
agent.py (bounded LangChain agent loop)
  ├── tools/search_tools.py      — search_linkedin, search_ats, search_web_jobs
  ├── tools/discovery_tools.py   — discover_company_career_page, discover_ats_platform
  ├── tools/job_tools.py         — fetch_job, extract_job_details
  ├── tools/evaluation_tools.py  — deterministic-first evaluation, AI fallback
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
2. **Agent searches** — chooses LinkedIn, ATS pages, or web search; results are persisted and deduplicated before entering the agent context
3. **Agent inspects** promising new jobs with `fetch_job`
4. **Agent evaluates** locally first; only ambiguous jobs use an additional LLM call
5. **Agent investigates** uncertain jobs within a strict per-job depth limit
6. **Agent notifies** via `notify_user` — PolicyEngine validates before Telegram
7. **Agent stops** when it has sufficient matches or an enforced tool/model budget is exhausted

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
| `MAX_MODEL_CALLS` | Outer agent turns per run (default `14`) |
| `MAX_LLM_EVALUATIONS` | Ambiguous-job LLM evaluations per run (default `6`) |
| `MAX_TOOL_CALLS` | All tool calls per run (default `48`) |
| `MAX_SEARCHES` | Search/discovery calls per run (default `12`) |
| `MAX_RESULTS_PER_SEARCH` | New results returned into context (default `12`) |

## Policy Layer (Deterministic)

The `PolicyEngine` enforces rules that the AI cannot bypass:
- Target company verification
- Duplicate notification prevention
- Excluded role/level filtering
- Daily notification rate limiting
- Location validation (India only)

## Execution Budgets

Physically enforced by middleware (not just prompt hints):
- 14 outer model calls
- 6 nested AI evaluations; later ambiguous jobs use the local fallback
- 48 total tool calls
- 12 search/discovery calls
- 8 notifications
- 2 evaluations per canonical job
- 5 minute timeout

Older tool inputs and results are cleared from the model view once the transcript
reaches roughly 10,000 tokens. Every run logs and persists model-call counts plus
input, output, total, and cached-input tokens in the `agent_runs` table.

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
