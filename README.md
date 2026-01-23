# 🎯 Job Tracker – Automated LinkedIn Job Monitor

A lightweight automation tool that continuously monitors LinkedIn for relevant job openings and sends instant alerts so you never miss an opportunity.

---

## 🧠 What This Application Does

- Periodically scans LinkedIn for new job postings using predefined role keywords.
- Focuses only on DevOps, Infrastructure, Cloud, and Security-related roles.
- Filters jobs from a fixed list of selected product-based companies.
- Restricts results to Bengaluru-based positions.
- Matches roles requiring 0–5 years of experience.
- Considers only recently posted jobs and ignores older listings.
- Tracks previously notified jobs to avoid duplicate alerts.
- Sends real-time job notifications to Telegram with role details and application links.
- Runs fully automatically using GitHub Actions with no server or manual intervention.

---

## 🛠️ Tech Stack Used

- **Language:** Python  
- **Automation:** GitHub Actions (cron-based scheduling)  
- **Data Fetching:** LinkedIn public job listings  
- **Notifications:** Telegram Bot API  
- **Storage:** JSON file tracked in GitHub (`seen_jobs.json`)  
- **Parsing & Requests:** Requests, BeautifulSoup  
- **Platform:** GitHub (free tier)

---

## ⚙️ How It Runs

The workflow executes on a schedule, fetches new jobs, applies filters, checks for duplicates, and sends alerts—completely hands-free.

---

Built as a practical automation project to demonstrate real-world problem solving, clean filtering logic, and production-style automation.
