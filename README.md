# 🎯 Job Tracker - Automated LinkedIn Job Monitor

An automated job tracking system that monitors LinkedIn for DevOps, Infrastructure, and Cloud Security roles from your target companies in Bengaluru and sends instant Telegram alerts when new positions are posted.

## ✨ Features

- 🔍 **Smart Job Search**: Monitors LinkedIn every 10 minutes for fresh job postings
- 🎯 **Targeted Filtering**: Only shows jobs from 33 pre-selected top companies (Microsoft, Amazon, Netflix, Adobe, etc.)
- 📍 **Location-Specific**: Filters for Bengaluru-based positions only
- 💼 **Experience Match**: Shows jobs requiring 0-5 years of experience
- ⏰ **Fresh Jobs Only**: Only alerts for jobs posted in the last 10 hours
- 📱 **Telegram Notifications**: Get instant alerts on your phone with job title, company, and direct application link
- 🚫 **No Duplicates**: Automatically tracks seen jobs to avoid repeat notifications
- 🚀 **Hands-Free**: Runs automatically on GitHub Actions - no server needed!

## 🔎 What Jobs Does It Track?

**Keywords:** Domain

**Target Companies (33):**
Mention the targeted companies

## 🚀 Setup Instructions

### 1. Fork or Clone This Repository
```bash
git clone https://github.com/YOUR_USERNAME/Job-Tracker-App.git
```

### 2. Get Your Telegram Bot Token
1. Open Telegram and search for [@BotFather](https://t.me/botfather)
2. Send `/newbot` and follow instructions to create your bot
3. Copy the token
4. Get your Chat ID:
   - Search for [@userinfobot](https://t.me/userinfobot) on Telegram
   - Send `/start` and copy your ID

### 3. Add GitHub Secrets
Go to your repository → **Settings** → **Secrets and variables** → **Actions** → **New repository secret**

Add these two secrets:
- **Name:** `TELEGRAM_TOKEN` | **Value:** Your bot token from BotFather
- **Name:** `TELEGRAM_CHAT_ID` | **Value:** Your chat ID from userinfobot

### 4. Enable GitHub Actions Workflow Permissions
Go to **Settings** → **Actions** → **General** → Scroll to **Workflow permissions**
- Select: ✅ **Read and write permissions**
- Click **Save**

### 5. Enable GitHub Actions
- Go to **Actions** tab in your repository
- If prompted, click **Enable workflows**

### 6. Test It! (Optional)
- Go to **Actions** → **Job Tracker** → **Run workflow**
- Click **"Run workflow"** button to test manually
- Check the workflow run logs and your Telegram for alerts

## 🎉 That's It!

The job tracker will now run automatically every 10 minutes. You'll receive Telegram notifications whenever a matching job is posted!

## 📝 How It Works

```
GitHub Actions (every 10 min)
    ↓
Fetch LinkedIn Jobs
    ↓
Filter by Keywords → Filter by Companies → Filter by Location/Experience
    ↓
Check if Already Seen?
    ↓
Send Telegram Alert → Save to seen_jobs.json → Commit to GitHub
```

## 🛠️ Customization

Want to modify the search criteria? Edit `config.json`:

- **target_companies**: Add/remove companies from the list
- **keywords**: Change job keywords to search for
- **career_page URL**: Modify location, experience level, or time filters

Then commit and push changes to GitHub.

## 🧪 Local Testing

Want to test before deploying?
```bash
# Install dependencies
pip install requests beautifulsoup4

# Run the tracker
python app.py
```

## 📊 Monitoring

- Check **Actions** tab to see workflow runs
- Each run shows logs of jobs found and alerts sent
- `seen_jobs.json` in your repo tracks all notified jobs

## ⚙️ Technical Details

- **Language**: Python 3.12
- **Platform**: GitHub Actions (free tier)
- **Scheduler**: Runs every 10 minutes via GitHub Actions cron
- **Storage**: Git repository (seen_jobs.json)
- **API**: LinkedIn public job search, Telegram Bot API

## 🤝 Contributing

Feel free to fork and customize for your own job search needs!

## 📄 License

MIT License - feel free to use and modify!
