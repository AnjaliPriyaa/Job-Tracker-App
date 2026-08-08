"""Notification tool — must go through PolicyEngine internally."""

import json
import logging
import os
from datetime import datetime, timezone

import requests
from langchain_core.tools import tool
from pydantic import BaseModel, Field

from policies.job_policy import PolicyEngine
from storage import JobRepository, NotificationRepository

logger = logging.getLogger(__name__)


class NotifyUserInput(BaseModel):
    canonical_id: str = Field(description="Job canonical ID to notify about")
    title: str = Field(description="Job title for the notification")
    company: str = Field(description="Company name")
    url: str = Field(description="Job posting URL")
    reason: str = Field(default="", description="Brief match reason")


@tool(args_schema=NotifyUserInput)
def notify_user(canonical_id: str, title: str, company: str, url: str, reason: str = "") -> str:
    """
    Send a Telegram notification for a matched job.

    IMPORTANT: This tool internally validates the notification through PolicyEngine.
    If the policy rejects it, a structured error is returned and nothing is sent.
    There is NO other way to send Telegram messages.
    """
    # --- Policy enforcement (deterministic, not AI) ---
    policy = PolicyEngine()
    policy_result = policy.validate_notification(canonical_id, company, title)

    if not policy_result.allowed:
        logger.info("PolicyEngine DENY: %s — %s", canonical_id, policy_result.reason)
        return json.dumps({
            "notified": False,
            "canonical_id": canonical_id,
            "error": policy_result.reason,
            "policy_decision": "deny",
        })

    # --- Send Telegram ---
    token = os.getenv("TELEGRAM_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")

    if not token or not chat_id:
        return json.dumps({"notified": False, "error": "Telegram not configured"})

    reason_short = reason[:120] + ("..." if len(reason) > 120 else "")
    message = f"🔔 *{title or 'New Job'}*\n🏢 {company}\n🔗 {url}\n_{reason_short}_"

    try:
        resp = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": message, "parse_mode": "Markdown"},
            timeout=10,
        )
        success = resp.status_code == 200 and resp.json().get("ok", False)
    except requests.RequestException as e:
        success = False
        logger.error("Telegram send failed: %s", e)

    # --- Record notification ---
    NotificationRepository.record(canonical_id, success)

    logger.info("Notification %s: %s at %s", "✓" if success else "✗", title, company)

    return json.dumps({
        "notified": success,
        "canonical_id": canonical_id,
        "error": None if success else "Telegram send failed",
        "policy_decision": "allow",
    })
