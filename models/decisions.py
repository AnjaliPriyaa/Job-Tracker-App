"""Evaluation and decision models."""

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class Decision(str, Enum):
    MATCH = "match"
    REJECT = "reject"
    INVESTIGATE = "investigate"


class EvaluationResult(BaseModel):
    """AI evaluation of a single job against user preferences."""
    decision: Decision = Field(description="match, reject, or investigate")
    score: float = Field(default=0.0, ge=0.0, le=1.0, description="Relevance score")
    confidence: float = Field(default=0.0, ge=0.0, le=1.0, description="Confidence in this decision")
    reasons: list[str] = Field(default_factory=list, description="Key factors in the decision")
    missing_information: list[str] = Field(default_factory=list, description="What we need to investigate further")
    needs_investigation: bool = Field(default=False, description="True if agent should dig deeper")
    investigation_depth: int = Field(default=0, ge=0, le=5, description="How many times this job has been investigated")


class InvestigationRequest(BaseModel):
    """Request from the agent to investigate an uncertain job."""
    job_id: str = Field(description="Which job to investigate")
    reason: str = Field(description="Why investigation is needed")
    suggested_tool: Optional[str] = Field(default=None, description="Suggested tool for investigation")
    suggested_query: Optional[str] = Field(default=None, description="What to search for")
