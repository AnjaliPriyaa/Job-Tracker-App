"""Deterministic-first job evaluation with a bounded AI fallback."""

import json
import logging
import os
import re
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv
from langchain_core.tools import tool
from pydantic import BaseModel, Field

from models.decisions import Decision, EvaluationResult

load_dotenv()
logger = logging.getLogger(__name__)


class EvaluateJobInput(BaseModel):
    """Only job-specific data crosses the outer agent boundary."""

    title: str = Field(description="Job title")
    company: str = Field(description="Company name")
    description: str = Field(description="Job description text")
    location: str = Field(default="", description="Job location")
    canonical_id: str = Field(default="", description="Canonical job ID")


_matcher = None


@lru_cache(maxsize=1)
def _load_preferences() -> dict:
    config_path = Path(__file__).resolve().parent.parent / "config.json"
    with open(config_path) as config_file:
        config = json.load(config_file)
    return {
        "target_companies": config.get("target_companies", []),
        "target_roles": config.get("roles", []),
        "keywords": config.get("job_portals", [{}])[0].get("keywords", []),
        "exclude_keywords": config.get("exclude_keywords", []),
        "exclude_roles": config.get("exclude_roles", []),
        "exclude_levels": config.get("exclude_levels", []),
        "max_experience": config.get("experience_years", 6),
        "min_experience": config.get("min_experience_years", 4),
    }


def _get_matcher():
    global _matcher
    if _matcher is None:
        from langchain_openai import ChatOpenAI

        deepseek_key = os.getenv("DEEPSEEK_API_KEY")
        if deepseek_key:
            _matcher = ChatOpenAI(
                model=os.getenv(
                    "DEEPSEEK_EVALUATION_MODEL",
                    os.getenv("DEEPSEEK_MODEL", "deepseek-chat"),
                ),
                temperature=0,
                max_tokens=int(os.getenv("EVALUATION_MAX_OUTPUT_TOKENS", "320")),
                openai_api_key=deepseek_key,
                openai_api_base="https://api.deepseek.com",
            ).with_structured_output(EvaluationResult, method="function_calling")
        else:
            _matcher = "fallback"
    return _matcher


def _contains_phrase(text: str, phrase: str) -> bool:
    phrase = phrase.lower().strip()
    return bool(phrase and re.search(rf"\b{re.escape(phrase)}\b", text.lower()))


def _company_allowed(company: str, targets: list[str]) -> bool:
    company_norm = " ".join(company.lower().replace(",", " ").split())
    return any(
        company_norm == " ".join(target.lower().replace(",", " ").split())
        or company_norm in target.lower()
        or target.lower() in company_norm
        for target in targets
    )


def _required_experience(text: str) -> int | None:
    """Return the minimum explicitly required years, not the top of a range."""
    patterns = [
        r"(?:minimum|at least|min\.?)\s*(?:of\s+)?(\d+)\s*\+?\s*years?",
        r"(\d+)\s*\+\s*years?",
        r"(\d+)\s*[-–]\s*\d+\s*years?",
    ]
    matches = [
        int(match.group(1))
        for pattern in patterns
        for match in re.finditer(pattern, text)
    ]
    return max(matches) if matches else None


def _result(decision: Decision, score: float, confidence: float, reason: str,
            missing: list[str] | None = None) -> EvaluationResult:
    return EvaluationResult(
        decision=decision,
        score=score,
        confidence=confidence,
        reasons=[reason],
        missing_information=missing or [],
        needs_investigation=decision == Decision.INVESTIGATE,
    )


def _deterministic_precheck(job: EvaluateJobInput, prefs: dict) -> EvaluationResult | None:
    """Resolve high-confidence cases locally; return None only for ambiguity."""
    title = job.title.strip()
    title_lower = title.lower()
    description = " ".join(job.description.split())
    text_lower = f"{title} {description}".lower()

    for phrase in [*prefs["exclude_roles"], *prefs["exclude_levels"]]:
        if _contains_phrase(title_lower, phrase):
            return _result(Decision.REJECT, 0.0, 0.99, f"Excluded title term '{phrase}'")

    for keyword in prefs["exclude_keywords"]:
        normalized = keyword.lower().strip()
        # A role word in prose (for example, "lead deployments") is not a title.
        search_all_text = (
            normalized in {"frontend", "ux design", "blockchain", "crypto", "web3"}
            or (any(char.isdigit() for char in normalized) and "year" in normalized)
        )
        haystack = text_lower if search_all_text else title_lower
        if normalized and normalized in haystack:
            return _result(Decision.REJECT, 0.05, 0.98, f"Excluded term '{keyword}'")

    if job.company and prefs["target_companies"] and not _company_allowed(
        job.company, prefs["target_companies"]
    ):
        return _result(Decision.REJECT, 0.0, 1.0, f"Company '{job.company}' is not targeted")

    if job.location:
        from policies.job_policy import PolicyEngine

        policy = PolicyEngine.__new__(PolicyEngine)
        if not policy.is_valid_location(job.location):
            return _result(Decision.REJECT, 0.0, 0.99, f"Location '{job.location}' is outside scope")

    required_experience = _required_experience(text_lower)
    if required_experience is not None and required_experience > prefs["max_experience"]:
        return _result(
            Decision.REJECT,
            0.1,
            0.97,
            f"Requires at least {required_experience} years (maximum is {prefs['max_experience']})",
        )

    if len(description) < 120:
        return _result(
            Decision.INVESTIGATE,
            0.35,
            0.95,
            "Description is too short for evaluation",
            ["full job description"],
        )

    title_matches = [role for role in prefs["target_roles"] if _contains_phrase(title, role)]
    keyword_matches = sorted({kw for kw in prefs["keywords"] if kw.lower() in text_lower})
    location_text = f"{job.location} {description[:500]}".lower()
    location_confirmed = any(
        marker in location_text
        for marker in ("bengaluru", "bangalore", "hyderabad", "india", "remote")
    )

    if job.company and title_matches and len(keyword_matches) >= 2 and location_confirmed:
        return EvaluationResult(
            decision=Decision.MATCH,
            score=min(0.95, 0.72 + 0.03 * len(keyword_matches)),
            confidence=0.9,
            reasons=[
                f"Target role '{title_matches[0]}' with {len(keyword_matches)} relevant skills",
                "Company, location, exclusions, and experience passed deterministic checks",
            ],
        )

    if not keyword_matches:
        return _result(
            Decision.INVESTIGATE,
            0.3,
            0.8,
            "No configured skills found",
            ["role relevance"],
        )

    return None


def _deterministic_fallback(job: EvaluateJobInput, prefs: dict) -> EvaluationResult:
    prechecked = _deterministic_precheck(job, prefs)
    if prechecked is not None:
        return prechecked

    text = f"{job.title} {job.description}".lower()
    matched = sorted({kw for kw in prefs["keywords"] if kw.lower() in text})
    if len(matched) >= 2:
        return EvaluationResult(
            decision=Decision.MATCH,
            score=min(0.88, 0.58 + len(matched) * 0.04),
            confidence=0.68,
            reasons=[f"Relevant skills: {', '.join(matched[:5])}"],
        )
    return _result(
        Decision.INVESTIGATE,
        0.4,
        0.55,
        "Ambiguous after local evaluation",
        ["role fit"],
    )


def _serialize(result: EvaluationResult, evaluation_mode: str) -> str:
    payload = result.model_dump(mode="json")
    payload["evaluation_mode"] = evaluation_mode
    return json.dumps(payload, separators=(",", ":"))


@tool(args_schema=EvaluateJobInput)
def evaluate_job(title: str, company: str, description: str,
                 location: str = "", canonical_id: str = "") -> str:
    """Evaluate one job locally first, using AI only when evidence is ambiguous."""
    from agent.middleware import get_budget

    budget = get_budget()
    if budget and canonical_id:
        block = budget.check_investigation(canonical_id)
        if block:
            return _serialize(
                _result(Decision.REJECT, 0.0, 1.0, block["reason"]),
                "budget",
            )

    job = EvaluateJobInput(
        title=title,
        company=company,
        description=description,
        location=location,
        canonical_id=canonical_id,
    )
    prefs = _load_preferences()
    deterministic = _deterministic_precheck(job, prefs)
    if deterministic is not None:
        logger.info(
            "evaluate_job: %s at %s -> %s (local)",
            title,
            company,
            deterministic.decision.value,
        )
        return _serialize(deterministic, "deterministic")

    if budget:
        block = budget.check_llm_evaluation()
        if block:
            return _serialize(_deterministic_fallback(job, prefs), "budget_fallback")

    matcher = _get_matcher()
    if matcher == "fallback" or matcher is None:
        result = _deterministic_fallback(job, prefs)
        mode = "deterministic_fallback"
    else:
        description_compact = " ".join(description.split())[:1600]
        role_families = ", ".join(dict.fromkeys(
            role.lower().replace("senior ", "") for role in prefs["target_roles"]
        ))
        prompt = (
            "Classify this pre-screened job as match, reject, or investigate. "
            "The company, hard exclusions, location policy, and explicit experience cap "
            "already passed local checks. Be conservative and request investigation only "
            "when decisive evidence is missing.\n"
            f"Target role families: {role_families}\n"
            f"Experience range: {prefs['min_experience']}-{prefs['max_experience']} years\n"
            f"Title: {title}\nCompany: {company}\nLocation: {location}\n"
            f"Description: {description_compact}"
        )
        try:
            result = matcher.invoke(prompt, config={"tags": ["evaluation"]})
            mode = "llm"
        except Exception as exc:
            logger.warning("AI evaluation failed: %s; using local fallback", exc)
            result = _deterministic_fallback(job, prefs)
            mode = "error_fallback"

    logger.info(
        "evaluate_job: %s at %s -> %s (%s)",
        title,
        company,
        result.decision.value,
        mode,
    )
    return _serialize(result, mode)
