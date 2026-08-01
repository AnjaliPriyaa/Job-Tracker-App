"""
AI-powered job matching using DeepSeek or Google Gemini via LangChain.

Supports multiple LLM providers:
  - DeepSeek (set DEEPSEEK_API_KEY) — uses deepseek-chat (V3)
  - Google Gemini (set GEMINI_API_KEY) — uses gemini-2.5-flash

Auto-detects which provider to use based on available API keys.
Set AI_PROVIDER=deepseek|gemini to force a specific provider when both keys are set.

Provides a JobMatcher class that evaluates whether a scraped job matches
the user's preferences (companies, roles, keywords, experience level).
"""

import json
import logging
import os
import re
from typing import Optional, Union

from dotenv import load_dotenv
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
# Provider resolution
# ---------------------------------------------------------------------------

def _resolve_provider() -> tuple[str, str]:
    """
    Determine which LLM provider to use.

    Returns (provider_name, model_name).
    Provider name is one of: 'deepseek', 'gemini', or empty string if none.
    """
    force = os.getenv("AI_PROVIDER", "").lower()
    has_deepseek = bool(os.getenv("DEEPSEEK_API_KEY"))
    has_gemini = bool(os.getenv("GEMINI_API_KEY"))

    if force == "deepseek" and has_deepseek:
        return ("deepseek", os.getenv("DEEPSEEK_MODEL", "deepseek-chat"))
    if force == "gemini" and has_gemini:
        return ("gemini", os.getenv("GEMINI_MODEL", "gemini-2.5-flash"))

    # Auto-detect: prefer DeepSeek if both are set (cheaper)
    if has_deepseek:
        return ("deepseek", os.getenv("DEEPSEEK_MODEL", "deepseek-chat"))
    if has_gemini:
        return ("gemini", os.getenv("GEMINI_MODEL", "gemini-2.5-flash"))

    return ("", "")


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
    min_experience: int = 0,
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

    # Check experience requirements
    # Reject high experience requirements (> max_experience)
    for pattern in [r"(\d+)\+\s*years?", r"(\d+)\s*[-–]\s*(\d+)\s*years?"]:
        for m in re.finditer(pattern, text):
            nums = [int(g) for g in m.groups() if g]
            if nums and max(nums) > max_experience:
                return MatchResult(match=False, confidence=0.8, reason=f"Requires {max(nums)}+ years experience")

    # Check for roles clearly below user's experience level
    # e.g., "1-2 years" when user has 6+ years — likely junior
    if min_experience > 0:
        for pattern in [r"(\d+)\s*[-–]\s*(\d+)\s*years?"]:
            for m in re.finditer(pattern, text):
                nums = [int(g) for g in m.groups() if g]
                if nums and max(nums) < min_experience - 1:
                    return MatchResult(match=False, confidence=0.75,
                                       reason=f"Requires only {max(nums)} years, below user's {min_experience}+")

    # Compute confidence based on keyword match density
    kw_ratio = len(matched_kw) / max(len(keywords), 1)
    confidence = 0.55 + (kw_ratio * 0.25)  # 0.55–0.80 range
    confidence = min(confidence, 0.8)

    return MatchResult(match=True, confidence=confidence, reason=f"Keyword match: {', '.join(matched_kw[:3])}")


# ---------------------------------------------------------------------------
# JobMatcher
# ---------------------------------------------------------------------------

class JobMatcher:
    """
    Evaluates job listings against user preferences using an LLM.

    Supports DeepSeek and Google Gemini.  Auto-detects the provider from
    environment variables.  Falls back to keyword matching when no API key
    is available.
    """

    def __init__(self, model_name: Optional[str] = None, temperature: float = 0.1):
        provider, detected_model = _resolve_provider()
        model = model_name or detected_model

        if provider == "deepseek":
            self._init_deepseek(model, temperature)
        elif provider == "gemini":
            self._init_gemini(model, temperature)
        else:
            logger.warning(
                "No API key found — set DEEPSEEK_API_KEY or GEMINI_API_KEY. "
                "AI matching disabled, using keyword fallback."
            )
            self._llm = None
            self._structured_llm = None
            self._provider = "none"

    def _init_deepseek(self, model: str, temperature: float) -> None:
        """Initialize DeepSeek via OpenAI-compatible ChatOpenAI."""
        from langchain_openai import ChatOpenAI

        self._provider = "deepseek"
        self._llm = ChatOpenAI(
            model=model,
            temperature=temperature,
            openai_api_key=os.getenv("DEEPSEEK_API_KEY"),
            openai_api_base="https://api.deepseek.com",
            max_tokens=512,
        )
        self._structured_llm = self._llm.with_structured_output(
            MatchResult, method="function_calling"
        )
        logger.info("AI matcher initialized: DeepSeek (%s)", model)

    def _init_gemini(self, model: str, temperature: float) -> None:
        """Initialize Google Gemini."""
        from langchain_google_genai import ChatGoogleGenerativeAI

        self._provider = "gemini"
        self._llm = ChatGoogleGenerativeAI(
            model=model,
            temperature=temperature,
            google_api_key=os.getenv("GEMINI_API_KEY"),
        )
        self._structured_llm = self._llm.with_structured_output(MatchResult)
        logger.info("AI matcher initialized: Gemini (%s)", model)

    # ------------------------------------------------------------------
    def match(
        self,
        title: str,
        company: str,
        description: str,
        *,
        keywords: list[str],
        target_companies: list[str],
        target_roles: Optional[list[str]] = None,
        exclude_keywords: Optional[list[str]] = None,
        exclude_roles: Optional[list[str]] = None,
        exclude_levels: Optional[list[str]] = None,
        max_experience: int = 6,
        min_experience: int = 0,
    ) -> MatchResult:
        """
        Evaluate a single job against the user's preferences.

        Returns a MatchResult with match/confidence/reason fields.
        """
        target_roles = target_roles or []
        exclude_keywords = exclude_keywords or []
        exclude_roles = exclude_roles or []
        exclude_levels = exclude_levels or []

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
        target_roles_str = ", ".join(target_roles)

        role_rule = ""
        if target_roles:
            role_rule = (
                f"0. The job role MUST align with one of these target roles: {target_roles_str}\n"
                f"   REJECT if the role is fundamentally different (e.g., a C/C++ networking role "
                f"is NOT a DevOps/Cloud/SRE role even if it mentions CI/CD in passing)\n"
            )

        min_exp_rule = ""
        if min_experience > 0:
            min_exp_rule = (f"8. REJECT if requires LESS than {min_experience} years experience "
                            f"(e.g., jobs asking for 1-3 years when user has {min_experience}+)")

        prompt = (
            f"Evaluate this job against the user's strict preferences.\n\n"
            f"Job Title: {title}\n"
            f"Company: {company}\n"
            f"Description (first 3000 chars):\n{description[:3000]}\n\n"
            f"--- STRICT MATCHING RULES ---\n"
            f"{role_rule}"
            f"1. Company MUST be in target list: {', '.join(target_companies)}\n"
            f"2. Title/description MUST contain at least one keyword: {', '.join(keywords)}\n"
            f"3. MUST NOT contain excluded keywords: {', '.join(exclude_keywords)}\n"
            f"4. REJECT if title contains: {exclude_roles_str}\n"
            f"5. REJECT if description mentions: {exclude_levels_str}\n"
            f"6. REJECT if requires MORE than {max_experience} years experience\n"
            f"7. REJECT if the core job function doesn't match the target roles\n"
            f"{min_exp_rule}\n"
            f"Be STRICT — reject if ANY rule is violated. Return your verdict as JSON."
        )

        try:
            if self._structured_llm is not None:
                result: MatchResult = self._structured_llm.invoke(prompt)
                logger.info("AI match (%s): %s at %s → match=%s (%.2f)",
                            self._provider, title, company, result.match, result.confidence)
                return result
            else:
                # No API key — use keyword fallback directly
                logger.info("Keyword match (no API key): %s at %s", title, company)
                return _keyword_fallback(
                    title, description, keywords, target_companies,
                    exclude_keywords, exclude_roles, exclude_levels, max_experience, min_experience,
                )
        except Exception as exc:
            logger.warning("AI matching failed, using fallback: %s", exc)
            return _keyword_fallback(
                title, description, keywords, target_companies,
                exclude_keywords, exclude_roles, exclude_levels, max_experience, min_experience,
            )
