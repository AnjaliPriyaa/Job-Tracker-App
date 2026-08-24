"""Evaluation tools — AI-powered job matching with structured output."""

import json
import logging
import os
import re
from typing import Optional

from dotenv import load_dotenv
from langchain_core.tools import tool
from pydantic import BaseModel, Field

from models.decisions import Decision, EvaluationResult

load_dotenv()
logger = logging.getLogger(__name__)


class EvaluateJobInput(BaseModel):
    title: str = Field(description="Job title")
    company: str = Field(description="Company name")
    description: str = Field(description="Full job description text")
    location: str = Field(default="", description="Job location")
    canonical_id: str = Field(default="", description="Canonical job ID for investigation tracking")
    target_companies: list[str] = Field(default_factory=list)
    target_roles: list[str] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)
    exclude_keywords: list[str] = Field(default_factory=list)
    exclude_roles: list[str] = Field(default_factory=list)
    exclude_levels: list[str] = Field(default_factory=list)
    max_experience: int = Field(default=6)
    min_experience: int = Field(default=4)


# Module-level AI matcher singleton
_matcher = None


def _get_matcher():
    global _matcher
    if _matcher is None:
        from langchain_openai import ChatOpenAI
        deepseek_key = os.getenv("DEEPSEEK_API_KEY")
        if deepseek_key:
            _matcher = ChatOpenAI(
                model=os.getenv("DEEPSEEK_MODEL", "deepseek-chat"),
                temperature=0.1,
                openai_api_key=deepseek_key,
                openai_api_base="https://api.deepseek.com",
            ).with_structured_output(EvaluationResult, method="function_calling")
        else:
            _matcher = "fallback"
    return _matcher


def _deterministic_fallback(job_input: EvaluateJobInput) -> EvaluationResult:
    """Zero-cost local evaluation when AI is unavailable."""
    text = f"{job_input.title} {job_input.description}".lower()

    # Excluded roles in title
    for role in job_input.exclude_roles:
        if role.lower() in job_input.title.lower():
            return EvaluationResult(decision=Decision.REJECT, score=0.0, confidence=0.99,
                                    reasons=[f"Excluded role '{role}' in title"])

    # Excluded keywords
    for kw in job_input.exclude_keywords:
        if kw.lower() in text:
            return EvaluationResult(decision=Decision.REJECT, score=0.1, confidence=0.85,
                                    reasons=[f"Excluded keyword '{kw}' found"])

    # Company check
    if job_input.company and job_input.target_companies:
        if not any(tc.lower() in job_input.company.lower() or job_input.company.lower() in tc.lower()
                   for tc in job_input.target_companies):
            return EvaluationResult(decision=Decision.REJECT, score=0.0, confidence=1.0,
                                    reasons=[f"Company '{job_input.company}' not in target list"])

    # Keyword match
    matched = [kw for kw in job_input.keywords if kw.lower() in text]
    if not matched:
        return EvaluationResult(decision=Decision.INVESTIGATE, score=0.3, confidence=0.4,
                                reasons=["No matching keywords found"],
                                missing_information=["role relevance"])

    # Experience
    exp_patterns = [r"(\d+)\+\s*years?", r"(\d+)\s*[-–]\s*(\d+)\s*years?"]
    for pat in exp_patterns:
        for m in re.finditer(pat, text):
            nums = [int(g) for g in m.groups() if g]
            if nums and max(nums) > job_input.max_experience:
                return EvaluationResult(decision=Decision.REJECT, score=0.2, confidence=0.8,
                                        reasons=[f"Requires {max(nums)}+ years (> {job_input.max_experience})"])

    kw_ratio = len(matched) / max(len(job_input.keywords), 1)
    score = 0.55 + kw_ratio * 0.3
    if job_input.location and "india" in job_input.location.lower():
        score += 0.1
    score = min(score, 0.9)

    return EvaluationResult(
        decision=Decision.MATCH if score >= 0.6 else Decision.INVESTIGATE,
        score=round(score, 2),
        confidence=0.5 + kw_ratio * 0.2,
        reasons=[f"Keywords matched: {', '.join(matched[:4])}"],
    )


@tool(args_schema=EvaluateJobInput)
def evaluate_job(
    title: str, company: str, description: str,
    location: str = "", canonical_id: str = "",
    target_companies: list[str] | None = None,
    target_roles: list[str] | None = None,
    keywords: list[str] | None = None,
    exclude_keywords: list[str] | None = None,
    exclude_roles: list[str] | None = None,
    exclude_levels: list[str] | None = None,
    max_experience: int = 6, min_experience: int = 4,
) -> str:
    """
    Evaluate a job against the user's strict criteria. Returns structured
    decision: match, reject, or investigate.
    Use this to determine if a job is worth notifying.
    """
    # Check investigation depth budget before evaluating
    from agent.middleware import get_budget
    budget = get_budget()
    if budget and canonical_id:
        block = budget.check_investigation(canonical_id)
        if block:
            return json.dumps({
                "decision": "reject",
                "score": 0.0,
                "confidence": 1.0,
                "reasons": [block["reason"]],
                "missing_information": [],
                "needs_investigation": False,
                "investigation_depth": block.get("depth", 0),
            })

    # Auto-load preferences from config if agent didn't pass them
    if not target_companies or not keywords:
        try:
            import json as _j
            from pathlib import Path as _P
            _cfg = _j.load(open(_P(__file__).resolve().parent.parent / "config.json"))
            target_companies = target_companies or _cfg.get("target_companies", [])
            target_roles = target_roles or _cfg.get("roles", [])
            keywords = keywords or _cfg.get("job_portals", [{}])[0].get("keywords", [])
            exclude_keywords = exclude_keywords or _cfg.get("exclude_keywords", [])
            exclude_roles = exclude_roles or _cfg.get("exclude_roles", [])
            exclude_levels = exclude_levels or _cfg.get("exclude_levels", [])
        except Exception:
            pass

    job_input = EvaluateJobInput(
        title=title, company=company, description=description, location=location,
        target_companies=target_companies or [], target_roles=target_roles or [],
        keywords=keywords or [], exclude_keywords=exclude_keywords or [],
        exclude_roles=exclude_roles or [], exclude_levels=exclude_levels or [],
        max_experience=max_experience, min_experience=min_experience,
    )

    matcher = _get_matcher()

    if matcher == "fallback" or matcher is None:
        result = _deterministic_fallback(job_input)
    else:
        try:
            target_roles_str = ", ".join(job_input.target_roles)
            exclude_roles_str = ", ".join(job_input.exclude_roles)

            prompt = f"""Evaluate this job against strict criteria.

Title: {title}
Company: {company}
Location: {location}
Description: {description[:2500]}

RULES:
- Company MUST be: {', '.join(job_input.target_companies)}
- Role MUST align with: {target_roles_str}
- Keywords: {', '.join(job_input.keywords)}
- Exclude if contains: {', '.join(job_input.exclude_keywords)}
- Reject roles: {exclude_roles_str}
- Experience: {min_experience}-{max_experience} years
- Location: Only Bengaluru, Hyderabad, India, or Remote

Return decision: match/reject/investigate with score, confidence, and reasons."""

            result: EvaluationResult = matcher.invoke(prompt)
        except Exception as exc:
            logger.warning("AI evaluation failed: %s, using fallback", exc)
            result = _deterministic_fallback(job_input)

    logger.info("evaluate_job: %s at %s → %s (%.2f)", title, company, result.decision.value, result.score)
    return result.model_dump_json()
