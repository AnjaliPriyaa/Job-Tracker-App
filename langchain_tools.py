"""Custom LangChain tools for job tracking agent"""
from langchain_core.tools import tool
from pydantic import BaseModel, Field
from typing import List, Dict, Optional
import json
import re
import utils


class JobSearchInput(BaseModel):
    """Input for job search tool"""
    url: str = Field(description="The LinkedIn job search URL to scrape")
    keywords: List[str] = Field(description="Keywords to match in job titles/descriptions")
    target_companies: List[str] = Field(description="List of target companies to search for")


class JobFilterInput(BaseModel):
    """Input for job filtering tool"""
    title: str = Field(description="Job title to filter")
    company: str = Field(description="Company name")
    description: str = Field(description="Job description")
    keywords: List[str] = Field(description="Keywords to match")
    exclude_keywords: List[str] = Field(description="Keywords to exclude")
    exclude_roles: List[str] = Field(description="Role keywords to exclude")
    exclude_levels: List[str] = Field(description="Level keywords to exclude")
    max_experience: int = Field(default=5, description="Maximum years of experience required")


class TelegramInput(BaseModel):
    """Input for Telegram notification tool"""
    message: str = Field(description="Message to send via Telegram")


class SeenJobsInput(BaseModel):
    """Input for managing seen jobs"""
    job_url: str = Field(description="Job URL to check or add")
    action: str = Field(description="Action: 'check' or 'add'")


@tool("scrape_linkedin_jobs", args_schema=JobSearchInput)
def scrape_linkedin_jobs(url: str, keywords: List[str], target_companies: List[str]) -> str:
    """
    Scrape job listings from LinkedIn job search URL.
    Returns a JSON string with list of jobs including title, company, and URL.
    """
    jobs = utils.scrape_jobs(url, target_companies)
    return json.dumps({"jobs": jobs, "count": len(jobs)})


@tool("get_job_description")
def get_job_description(job_url: str) -> str:
    """
    Fetch the full job description from a LinkedIn job URL.
    Returns the complete job description text.
    """
    description = utils.get_job_description(job_url)
    if description:
        return json.dumps({"description": description, "url": job_url})
    return json.dumps({"error": "Could not find job description"})


@tool("filter_job_by_criteria", args_schema=JobFilterInput)
def filter_job_by_criteria(
    title: str,
    company: str,
    description: str,
    keywords: List[str],
    exclude_keywords: List[str],
    exclude_roles: List[str],
    exclude_levels: List[str],
    max_experience: int = 5
) -> str:
    """
    Filter a job based on matching criteria.
    Returns a JSON string with match status, confidence score, and reason.
    This is a rule-based filter that checks keywords and exclusions.
    """
    title_lower = title.lower()
    desc_lower = description.lower()
    
    # Check for excluded roles in title
    for role in exclude_roles:
        if role.lower() in title_lower:
            return json.dumps({
                "match": False,
                "confidence": 1.0,
                "reason": f"Title contains excluded role: {role}"
            })
    
    # Check for excluded levels
    for level in exclude_levels:
        if level.lower() in title_lower or level.lower() in desc_lower:
            return json.dumps({
                "match": False,
                "confidence": 0.9,
                "reason": f"Contains excluded level: {level}"
            })
    
    # Check for excluded keywords
    for kw in exclude_keywords:
        if kw.lower() in desc_lower:
            return json.dumps({
                "match": False,
                "confidence": 0.85,
                "reason": f"Contains excluded keyword: {kw}"
            })
    
    # Check for matching keywords
    matched_keywords = [kw for kw in keywords if kw.lower() in title_lower or kw.lower() in desc_lower]
    
    if not matched_keywords:
        return json.dumps({
            "match": False,
            "confidence": 0.8,
            "reason": "No matching keywords found"
        })
    
    # Check experience requirements
    exp_patterns = [
        r'(\d+)\+?\s*years?\s+(?:of\s+)?experience',
        r'(\d+)-(\d+)\s*years?',
        r'minimum\s+(?:of\s+)?(\d+)\s*years?'
    ]
    
    for pattern in exp_patterns:
        matches = re.findall(pattern, desc_lower)
        if matches:
            for match in matches:
                # Handle tuple from range pattern
                exp_req = int(match[0]) if isinstance(match, tuple) else int(match)
                if exp_req > max_experience:
                    return json.dumps({
                        "match": False,
                        "confidence": 0.95,
                        "reason": f"Requires {exp_req} years experience (max {max_experience})"
                    })
    
    return json.dumps({
        "match": True,
        "confidence": 0.9,
        "reason": f"Matched keywords: {', '.join(matched_keywords)} at {company}"
    })


@tool("send_telegram_notification", args_schema=TelegramInput)
def send_telegram_notification(message: str) -> str:
    """
    Send a notification message via Telegram.
    Returns success or error status.
    """
    if utils.send_telegram(message):
        return json.dumps({"success": True, "message": "Notification sent"})
    return json.dumps({"success": False, "error": "Failed to send notification"})


@tool("manage_seen_jobs", args_schema=SeenJobsInput)
def manage_seen_jobs(job_url: str, action: str) -> str:
    """
    Manage the list of seen jobs.
    Actions: 'check' - check if job was seen before, 'add' - add job to seen list.
    Returns the result as JSON.
    """
    try:
        # Load existing seen jobs
        seen_jobs = utils.load_seen_jobs()
        
        if action == "check":
            is_seen = job_url in seen_jobs
            return json.dumps({"seen": is_seen, "url": job_url})
        
        elif action == "add":
            seen_jobs.add(job_url)
            utils.save_seen_jobs(seen_jobs)
            return json.dumps({"added": True, "url": job_url, "total_seen": len(seen_jobs)})
        
        else:
            return json.dumps({"error": f"Invalid action: {action}"})
    
    except Exception as e:
        return json.dumps({"error": str(e)})


@tool("check_cleanup_needed")
def check_cleanup_needed() -> str:
    """
    Check if cleanup of seen jobs is needed (after 10 days).
    If needed, clears the seen jobs file.
    Returns cleanup status.
    """
    try:
        # Use utility function to perform cleanup
        import io
        import sys
        
        # Capture output
        old_stdout = sys.stdout
        sys.stdout = buffer = io.StringIO()
        
        utils.check_and_cleanup()
        
        output = buffer.getvalue()
        sys.stdout = old_stdout
        
        if "performed" in output:
            return json.dumps({
                "cleanup_done": True,
                "reason": "Cleanup performed",
                "next_cleanup": utils.CLEANUP_DAYS
            })
        elif "Initialized" in output:
            return json.dumps({
                "cleanup_done": False,
                "reason": "First run - initialized"
            })
        else:
            return json.dumps({
                "cleanup_done": False,
                "reason": "No cleanup needed"
            })
    
    except Exception as e:
        return json.dumps({"error": str(e)})


@tool("load_config")
def load_config() -> str:
    """
    Load the configuration file containing job search criteria,
    target companies, keywords, and exclusions.
    Returns config as JSON string.
    """
    try:
        config = utils.load_config()
        return json.dumps(config)
    except Exception as e:
        return json.dumps({"error": f"Failed to load config: {str(e)}"})


# Export all tools
ALL_TOOLS = [
    scrape_linkedin_jobs,
    get_job_description,
    filter_job_by_criteria,
    send_telegram_notification,
    manage_seen_jobs,
    check_cleanup_needed,
    load_config
]
