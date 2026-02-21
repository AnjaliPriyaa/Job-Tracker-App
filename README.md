# Agentic Job Tracker 🤖

Autonomous AI agent using **LangChain** that searches, filters, and notifies you about relevant job opportunities.

## 🚀 What Makes It Agentic

This isn't just a script - it's an **autonomous AI agent** that:
- ✅ Makes intelligent decisions about job matches
- ✅ Uses custom LangChain tools to interact with services
- ✅ Reasons through multi-step workflows
- ✅ Adapts to different scenarios autonomously
- ✅ Maintains context and memory
- ✅ Explains its decision-making process

## 📋 Features

- **Autonomous Operation**: Runs end-to-end without human intervention
- **AI-Powered Filtering**: Uses Google Gemini for intelligent job matching
- **Multi-Role Support**: Track multiple job roles simultaneously
- **Company Targeting**: Focus on 41+ target companies
- **Smart Exclusions**: Filters by experience, keywords, and levels
- **Telegram Notifications**: Real-time alerts for new matches
- **Auto Cleanup**: Manages state and cleans up old data every 10 days

## 🛠️ Quick Setup

1. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

2. **Set environment variables** (`.env` file):
   ```
   GEMINI_API_KEY=your_gemini_api_key
   TELEGRAM_TOKEN=your_telegram_bot_token
   TELEGRAM_CHAT_ID=your_chat_id
   ```

3. **Customize `config.json`:**
   - Update `roles` with job titles you want
   - Modify `target_companies` list
   - Adjust `experience_years` threshold
   - Add `exclude_keywords` and `exclude_roles`

4. **Run the agent:**
   ```bash
   python agent_app_simple.py
   ```

## 📊 Configuration Example

**config.json:**
```json
{
  "roles": [
    "Senior DevOps Engineer",
    "Cloud Engineer",
    "Site Reliability Engineer"
  ],
  "experience_years": 5,
  "target_companies": ["Google", "Microsoft", "Amazon"],
  "exclude_roles": ["manager", "director", "lead"],
  "exclude_keywords": ["frontend", "architect"]
}
```

## 🎯 How It Works

**Autonomous Workflow:**
```
Load Config → Check Cleanup → Scrape Jobs → Fetch Descriptions 
→ AI Analysis → Decision Making → Notify/Track → Save State
```

The agent autonomously:
1. **Loads** your configuration and preferences
2. **Scrapes** job listings from LinkedIn
3. **Fetches** full job descriptions
4. **Filters** using exclude rules
5. **Analyzes** with AI (Gemini) for match quality
6. **Decides** whether to notify, track, or reject
7. **Sends** Telegram notifications for matches
8. **Tracks** seen jobs to avoid duplicates
9. **Cleans** up old data every 10 days

## 📁 Key Files

- **agent_app_simple.py** - Main agentic application (recommended)
- **agent_app.py** - Advanced ReAct agent version
- **langchain_tools.py** - Custom LangChain tools (7 tools)
- **langchain_ai.py** - AI matching with Gemini
- **config.json** - Your search criteria
- **test_setup.py** - Verify installation

## 📚 Documentation

- **[QUICKSTART.md](QUICKSTART.md)** - Get started in 3 minutes
- **[LANGCHAIN_README.md](LANGCHAIN_README.md)** - Full documentation
- **[COMPARISON.py](COMPARISON.py)** - Architecture deep dive

## 🔧 LangChain Tools

The agent uses these custom tools:
1. `scrape_linkedin_jobs` - Scrape job listings
2. `get_job_description` - Fetch full descriptions
3. `filter_job_by_criteria` - Rule-based filtering
4. `ai_match_job` - AI-powered matching
5. `send_telegram_notification` - Send alerts
6. `manage_seen_jobs` - Track state
7. `check_cleanup_needed` - Auto cleanup

## 🤖 Why Agentic?

Traditional scripts execute fixed steps. This **agentic system**:
- Makes autonomous decisions based on AI reasoning
- Adapts workflow based on results
- Uses tools like a human would
- Maintains context across operations
- Explains its decision-making process
- Can be easily extended with new tools

## 📈 Example Output

```
🤖 Agentic Job Tracker Started

📋 Step 1: Checking cleanup requirements...
✓ No cleanup needed (3/10 days)

📋 Step 2: Loading seen jobs...
   Tracking 45 previously seen jobs

📋 Step 3: Searching job portals...

  🔍 Analyzing: Senior DevOps Engineer at Google
     🤖 AI Match: True (confidence: 0.85)
     🎯 Decision: NOTIFY
     ✅ Notification sent!

📊 FINAL REPORT
   Total jobs found: 12
   New jobs discovered: 3
   Notifications sent: 3
```

## ⚙️ GitHub Actions (Optional)

Set up automated runs every 20 minutes:

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

## 🆘 Troubleshooting

**No jobs found?**
- Verify LinkedIn URL in config.json
- Check target_companies match exactly
- Ensure API keys are set correctly

**Too many/few matches?**
- Adjust `experience_years` threshold
- Update `exclude_keywords` list
- Modify confidence threshold in code (default 0.6)

**Setup issues?**
- Run `python test_setup.py` to diagnose
- Check all packages are installed
- Verify .env file exists with correct keys

## 📄 License

MIT License - Feel free to use and modify!

## 🙏 Credits

Built with:
- [LangChain](https://python.langchain.com/) - Agent framework
- [Google Gemini](https://ai.google.dev/) - AI model
- [Beautiful Soup](https://www.crummy.com/software/BeautifulSoup/) - Web scraping

---

**Read the full story on Medium:**
- [Part 1: Building the Job Tracker](https://medium.com/@anjalipriya_/i-built-a-job-tracker-that-pings-me-when-my-dream-companies-post-new-roles-d71581406753)
- [Part 2: Adding AI](https://medium.com/@anjalipriya_/why-my-job-tracker-needed-ai-and-how-it-changed-everything-c72d1d3cb21d)
- Part 3: Agentic AI (Coming Soon!)

---

Made with ❤️ using LangChain and Google Gemini
