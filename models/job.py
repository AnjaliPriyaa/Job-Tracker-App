"""Job and source models with hierarchical deduplication."""

from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class JobStatus(str, Enum):
    DISCOVERED = "discovered"
    EVALUATING = "evaluating"
    MATCHED = "matched"
    REJECTED = "rejected"
    INVESTIGATING = "investigating"
    NOTIFIED = "notified"
    DUPLICATE = "duplicate"


class JobSource(BaseModel):
    """A job listing from a specific source."""
    source: str = Field(description="Source platform: linkedin, greenhouse, lever, ashby, web")
    source_job_id: str = Field(description="Platform-specific job ID")
    url: str = Field(description="Canonical URL for this job")
    title: str = Field(default="")
    company: str = Field(default="")
    location: str = Field(default="")
    description: str = Field(default="")


class Job(BaseModel):
    """Canonical job record with deduplication support."""
    canonical_id: str = Field(description="Primary dedup key: source:source_job_id")
    sources: list[JobSource] = Field(default_factory=list, description="All sources that found this job")

    # Normalized fields for secondary dedup
    company_normalized: str = Field(default="", description="Lowercased, stripped company name")
    title_normalized: str = Field(default="", description="Lowercased, stripped job title")
    location_normalized: str = Field(default="", description="Lowercased location")

    status: JobStatus = Field(default=JobStatus.DISCOVERED)
    first_seen: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    last_seen: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    notified: bool = False

    @staticmethod
    def normalize(text: str) -> str:
        """Normalize text for secondary dedup matching."""
        return " ".join(text.lower().strip().split())

    @staticmethod
    def make_canonical_id(source: str, source_job_id: str) -> str:
        return f"{source}:{source_job_id}"

    def matches_secondary(self, company: str, title: str, location: str) -> bool:
        """Check if this job matches the given normalized fields."""
        return (
            self.company_normalized == self.normalize(company)
            and self.title_normalized == self.normalize(title)
            and self.location_normalized == self.normalize(location)
        )

    def add_source(self, src: JobSource) -> None:
        """Add a source if not already present."""
        if not any(s.url == src.url for s in self.sources):
            self.sources.append(src)
            self.last_seen = datetime.now(timezone.utc).isoformat()
