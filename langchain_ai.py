"""
AI-powered job matching using Google Gemini via LangChain.

Provides a JobMatcher class that evaluates whether a scraped job matches
the user's preferences (companies, roles, keywords, experience level).
"""

import json
import logging
import os
from typing import Optional

from dotenv import load_dotenv
from langchain_google_genai import ChatGoogleGenerativeAI
from pydantic import BaseModel, Field

load_dotenv()

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Structured output model
# ---------------------------------------------------------------------------

class MatchResult(BaseModel):
    """Structured result from the AI job matcher."""
    match: bool = Field(description="Whether the job is a match")
    confidence: float = Field(
        ge=0.0, le=1.0, description="Confidence score (0.0-1.0)"
    )
    reason: str = Field(description="Brief explanation of the decision")


# ---------------------------------------------------------------------------
# Fallback keyword matching (no API call needed)
# ---------------------------------------------------------------------------

def _keyword_fallback(
    title: str,
    description: str,
    keywords: list[str],
    target_companies: list[str],
    exclude_keywords: list[str],
    exclude_roles: list[str],
    exclude_levels: list[str],
    max_experience: int,
) -> MatchResult:
    """Fast local check when the AI call fails — strict keyword matching."""
    text = f"{title} {description}".lower()

    # Excluded roles in title → immediate reject
    for role in exclude_roles:
        if role.lower() in title.lower():
            return MatchResult(match=False, confidence=0.95, reason=f"Excluded role '{role}' in title")

    # Excluded levels anywhere
    for level in exclude_levels:
        if level.lower() in text:
            return MatchResult(match=False, confidence=0.85, reason=f"Excluded level '{level}' found")

    # Excluded keywords
    for kw in exclude_keywords:
        if kw.lower() in text:
            return MatchResult(match=False, confidence=0.85, reason=f"Excluded keyword '{kw}' found")

    # Must have at least one positive keyword
    matched_kw = [kw for kw in keywords if kw.lower() in text]
    if not matched_kw:
        return MatchResult(match=False, confidence=0.7, reason="No matching keywords found")

    # Reject high experience requirements
    import re
    for pattern in [r"(\d+)\+\s*years?", r"(\d+)\s*[-–]\s*(\d+)\s*years?"]:
        for m in re.finditer(pattern, text):
            nums = [int(g) for g in m.groups() if g]
            if nums and max(nums) > max_experience:
                return MatchResult(match=False, confidence=0.8, reason=f"Requires {max(nums)}+ years experience")

    return MatchResult(match=True, confidence=0.6, reason=f"Keyword match: {', '.join(matched_kw[:3])}")


# ---------------------------------------------------------------------------
# JobMatcher
# ---------------------------------------------------------------------------

class JobMatcher:
    """Evaluates job listings against user preferences using Gemini."""

    def __init__(self, model_name: str = "gemini-2.5-flash", temperature: float = 0.1):
        api_key = os.getenv("GEMINI_API_KEY")

        if api_key:
            self._llm = ChatGoogleGenerativeAI(
                model=model_name,
                temperature=temperature,
                google_api_key=api_key,
            )
            self._structured_llm = self._llm.with_structured_output(MatchResult)
        else:
            logger.warning("GEMINI_API_KEY not set — AI matching disabled, using keyword fallback")
            self._llm = None
            self._structured_llm = None

    # ------------------------------------------------------------------
    def match(
        self,
        title: str,
        company: str,
        description: str,
        *,
        keywords: list[str],
        target_companies: list[str],
        exclude_keywords: list[str],
        exclude_roles: list[str],
        exclude_levels: list[str],
        max_experience: int = 6,
    ) -> MatchResult:
        """
        Evaluate a single job against the user's preferences.

        Returns a MatchResult with match/confidence/reason fields.
        """
        # Quick pre-check: excluded role in title → skip AI call entirely
        title_lower = title.lower()
        for role in exclude_roles:
            if role.lower() in title_lower:
                return MatchResult(
                    match=False, confidence=0.99,
                    reason=f"Title contains excluded role: '{role}'",
                )

        # Build the prompt
        exclude_roles_str = ", ".join(f'"{r}"' for r in exclude_roles)
        exclude_levels_str = ", ".join(f'"{l}"' for l in exclude_levels)

        prompt = (
            f"Evaluate this job against the user's strict preferences.\n\n"
            f"Job Title: {title}\n"
            f"Company: {company}\n"
            f"Description (first 3000 chars):\n{description[:3000]}\n\n"
            f"--- STRICT MATCHING RULES ---\n"
            f"1. Company MUST be in target list: {', '.join(target_companies)}\n"
            f"2. Title/description MUST contain at least one keyword: {', '.join(keywords)}\n"
            f"3. MUST NOT contain excluded keywords: {', '.join(exclude_keywords)}\n"
            f"4. REJECT if title contains: {exclude_roles_str}\n"
            f"5. REJECT if description mentions: {exclude_levels_str}\n"
            f"6. REJECT if requires MORE than {max_experience} years experience\n\n"
            f"Be STRICT — reject if ANY rule is violated. Return your verdict as JSON."
        )

        try:
            if self._structured_llm is not None:
                result: MatchResult = self._structured_llm.invoke(prompt)
                logger.info("AI match: %s at %s → match=%s (%.2f)", title, company, result.match, result.confidence)
                return result
            else:
                # No API key — use keyword fallback directly
                logger.info("Keyword match (no API key): %s at %s", title, company)
                return _keyword_fallback(
                    title, description, keywords, target_companies,
                    exclude_keywords, exclude_roles, exclude_levels, max_experience,
                )
        except Exception as exc:
            logger.warning("AI matching failed, using fallback: %s", exc)
            return _keyword_fallback(
                title, description, keywords, target_companies,
                exclude_keywords, exclude_roles, exclude_levels, max_experience,
            )
