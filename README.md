# Agentic Job Tracker

A job tracker that searches for DevOps, Cloud, SRE, and Platform Engineering jobs, evaluates them against your criteria, and notifies you via Telegram. The scheduled entry point uses a bounded, knowledge-guided decision loop and **zero model tokens**; the optional LLM agent remains in `agent.py`.

## What Makes This Agentic?

In scheduled key-free runs, the controller selects a source skill, observes new jobs and failures, remembers which companies it tried, verifies first-party details, and stops when its time or notification budget is reached. It prioritizes previously unsearched companies while checking high-priority custom adapters regularly. Nothing in this loop calls a model.

When explicitly run with a working model key, the **LLM agent decides what to do**. The agent:
- Chooses which search tools to use based on what it discovers
- Investigates uncertain jobs instead of blindly accepting/rejecting
- Recovers from tool failures by trying alternative approaches
- Decides when enough jobs have been found
- Adapts its strategy dynamically

The system provides **tools** (search, discover, fetch, evaluate, notify) and the agent uses them autonomously. Deterministic logic handles **policy enforcement and obvious job decisions** (security, rate limiting, dedup, hard exclusions, clear matches); it does not orchestrate the workflow.

## Architecture

```
agent.py (bounded LangChain agent loop)
  ├── tools/search_tools.py      — LinkedIn, first-party careers, ATS, web search
  ├── tools/company_careers.py   — verified company-domain career-page parsers
  ├── career_knowledge.json      — 90 company-domain source candidates
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

For an optional model-based run:

1. **Agent gets preferences** via `get_user_preferences`
2. **Agent searches** — chooses LinkedIn, verified first-party careers, ATS pages, or web search; results are persisted and deduplicated before entering the agent context
3. **Agent inspects** promising new jobs with `fetch_job`
4. **Agent evaluates** locally first; only ambiguous jobs use an additional LLM call
5. **Agent investigates** uncertain jobs within a strict per-job depth limit
6. **Agent notifies** via `notify_user` — PolicyEngine validates before Telegram
7. **Agent stops** when it has sufficient matches or an enforced tool/model budget is exhausted

## Quick Setup

```bash
pip install -r requirements.txt
cp .env.example .env
# For local key-free operation, set TELEGRAM_TOKEN and TELEGRAM_CHAT_ID in .env
RUN_CONTEXT=career python free_run.py
```

## Configuration

Edit `config.json`:
- `target_companies` — companies to monitor
- `roles` — target job roles
- `experience_years` / `min_experience_years`
- `confidence_threshold`
- `exclude_roles`, `exclude_levels`, `exclude_keywords`
- `company_career_pages` — verified first-party pages and allowed company-owned hosts
- `company_career_seeds` — verified entry pages for selected generic readers
- `career_knowledge.json` — company-owned domain candidates for all 90 targets

The first-party career mode has custom, live-checked adapters for **Apple,
Google, and Microsoft**. All 90 target companies are in the source knowledge
base. For the remaining companies, a bounded generic skill tries the company's
domain and internal careers links, then requires a live company-owned job detail
page, relevant title, India location, and substantial description. A domain in
the knowledge base is a **source candidate, not a verified open role**. Some
JavaScript-only sites will need a custom adapter before they yield jobs; the
app reports no result instead of inventing one or switching to an ATS board.
`career_source_state` in SQLite remembers attempts so companies skipped due to
a short run are tried ahead of recently checked ones. The separate optional
`RUN_CONTEXT=ats` mode retains Greenhouse/Lever/Ashby searching.

## Environment Variables

| Variable | Description |
|---|---|
| `AI_PROVIDER` | Optional `agent.py` provider: `gemini` (default) or `deepseek`; `free_run.py` always uses rules |
| `GEMINI_API_KEY` | Optional Gemini API key for `agent.py`; GitHub Actions does not use it |
| `DEEPSEEK_API_KEY` | Optional DeepSeek key, inactive unless `AI_PROVIDER=deepseek` |
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

The optional LLM agent has physically enforced middleware limits (not just prompt hints):
- 14 outer model calls
- 6 nested AI evaluations; later ambiguous jobs use the local fallback
- 48 total tool calls
- 12 search/discovery calls
- 8 notifications
- 2 evaluations per canonical job
- 5 minute timeout

The scheduled key-free controller can use up to 24 source searches, 72 tool
calls, and five minutes per run. Its model-token counters are always zero.

Older tool inputs and results are cleared from the model view once the transcript
reaches roughly 10,000 tokens. Every run logs and persists model-call counts plus
input, output, total, and cached-input tokens in the `agent_runs` table.

## GitHub Actions

Two workflows exist but are currently **disabled on GitHub**. When re-enabled,
they invoke `free_run.py` with different run contexts and use no model provider.

| Workflow | Schedule | Context |
|---|---|---|
| `linkedin-run.yml` | Every 2 hours | LinkedIn-focused initial search |
| `career-run.yml` | Daily 10 AM IST (4:30 UTC) | Verified first-party company career pages |

Both share the same SQLite state, tools, policies, and budget infrastructure.
The workflows run `free_run.py`, which uses the existing
search, evaluation, deduplication, policy, and Telegram tools without any model
API key or model tokens. Both Gemini and DeepSeek are commented out in the
workflow files because the saved Gemini key is invalid and the DeepSeek account
has insufficient balance. `agent.py` remains available for agentic runs once a
working model key is configured. ATS boards remain available separately with
`RUN_CONTEXT=ats python free_run.py` and are not used by the Career Pages workflow.
The workflows check out the latest `main`
when they start, so a queued run does not try to push database changes from an
outdated commit.

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
