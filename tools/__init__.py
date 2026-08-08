"""Agent tools for the job tracker."""

from tools.search_tools import search_linkedin, search_web_jobs, search_ats
from tools.discovery_tools import discover_company_career_page, discover_ats_platform
from tools.job_tools import fetch_job, extract_job_details
from tools.evaluation_tools import evaluate_job
from tools.query_tools import generate_linkedin_queries, get_search_keywords
from tools.state_tools import (
    get_seen_jobs, save_job, record_decision, record_notification,
    get_user_preferences, get_job_history,
)
from tools.notification_tools import notify_user

ALL_TOOLS = [
    # Search
    search_linkedin, search_web_jobs, search_ats,
    # Query generation
    generate_linkedin_queries, get_search_keywords,
    # Discovery
    discover_company_career_page, discover_ats_platform,
    # Job inspection
    fetch_job, extract_job_details,
    # Evaluation
    evaluate_job,
    # State
    get_seen_jobs, save_job, record_decision, record_notification,
    get_user_preferences, get_job_history,
    # Notification
    notify_user,
]
