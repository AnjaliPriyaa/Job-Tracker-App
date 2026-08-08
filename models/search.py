"""Search models for agent queries and results."""

from typing import Optional

from pydantic import BaseModel, Field


class SearchQuery(BaseModel):
    """A search request from the agent."""
    query: str = Field(description="Search keywords or role title")
    location: Optional[str] = Field(default=None, description="Location filter")
    company: Optional[str] = Field(default=None, description="Company to search for")
    source: Optional[str] = Field(default=None, description="Source platform hint")
    max_results: int = Field(default=20, ge=1, le=100)


class SearchResult(BaseModel):
    """Result from a search tool."""
    source: str = Field(description="Platform that provided the result")
    source_job_id: str = Field(description="Platform-specific job ID")
    url: str = Field(description="Job posting URL")
    title: str = Field(default="")
    company: str = Field(default="")
    location: str = Field(default="")
    snippet: str = Field(default="", description="Short text preview")
    error: Optional[str] = Field(default=None, description="Error message if search failed")
