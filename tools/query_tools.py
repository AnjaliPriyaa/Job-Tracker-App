"""
Dynamic query generation tools.

Generates LinkedIn search URLs and web search queries from user preferences,
enabling the agent to search with role variants, technology filters, and
location combinations rather than a single fixed query.
"""

import json
import logging
from urllib.parse import quote

from langchain_core.tools import tool
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


def _load_config():
    import json as _json
    from pathlib import Path as _Path
    _config_path = _Path(__file__).resolve().parent.parent / "config.json"
    with open(_config_path) as _f:
        return _json.load(_f)


def _load_preferences():
    """Load all user preferences for query generation."""
    config = _load_config()
    return {
        "roles": config.get("roles", []),
        "keywords": config.get("job_portals", [{}])[0].get("keywords", []),
        "target_companies": config.get("target_companies", []),
        "exclude_roles": config.get("exclude_roles", []),
        "exclude_keywords": config.get("exclude_keywords", []),
        "experience_years": config.get("experience_years", 6),
        "min_experience_years": config.get("min_experience_years", 4),
    }


class GenerateQueriesInput(BaseModel):
    focus: str = Field(
        default="broad",
        description="Search focus: 'broad' (general), 'role' (role-specific), "
                    "'technology' (tech-focused), 'company' (company-specific)"
    )
    count: int = Field(default=5, ge=1, le=20, description="Number of queries to generate")


@tool(args_schema=GenerateQueriesInput)
def generate_linkedin_queries(focus: str = "broad", count: int = 5) -> str:
    """
    Generate dynamic LinkedIn search URLs based on user preferences.
    Creates multiple query variants covering different role/technology combinations.

    Use this to get a variety of search URLs, then call search_linkedin with each
    one to find jobs across different query dimensions.
    """
    prefs = _load_preferences()
    roles = prefs["roles"]
    keywords = prefs["keywords"]
    companies = prefs["target_companies"]
    exclude = prefs.get("exclude_keywords", [])

    queries = []
    location = quote("Bengaluru, India")

    # Core DevOps/Cloud technologies for filtering
    tech_groups = {
        "core": "kubernetes OR docker OR terraform OR ansible OR jenkins",
        "cloud": "aws OR azure OR gcp OR cloud",
        "cicd": "CI/CD OR github actions OR gitlab OR jenkins OR argo",
        "monitoring": "prometheus OR grafana OR datadog OR elk OR splunk",
        "iac": "terraform OR pulumi OR cloudformation OR ansible OR puppet",
    }

    # Role-based queries
    if focus in ("broad", "role"):
        for role in roles[:count]:
            q = f'("{role}") AND ({tech_groups["core"]})'
            url = f"https://www.linkedin.com/jobs/search/?keywords={quote(q)}&location={location}&f_TPR=r54000&f_E=3,4"
            queries.append({"query": role, "url": url, "type": "role"})

    # Technology-focused queries
    if focus in ("broad", "technology"):
        for tech_name, tech_query in list(tech_groups.items())[:min(count, len(tech_groups))]:
            role_part = " OR ".join(f'"{r}"' for r in roles[:3])
            q = f"({role_part}) AND ({tech_query})"
            url = f"https://www.linkedin.com/jobs/search/?keywords={quote(q)}&location={location}&f_TPR=r54000&f_E=3,4"
            queries.append({"query": tech_name, "url": url, "type": "technology"})

    # Company-specific searches (for top target companies)
    if focus in ("broad", "company"):
        for company in companies[:count]:
            role_part = " OR ".join(f'"{r}"' for r in roles[:3])
            q = f'({role_part}) AND "{company}"'
            url = f"https://www.linkedin.com/jobs/search/?keywords={quote(q)}&location={location}&f_TPR=r604800"
            queries.append({"query": company, "url": url, "type": "company"})

    # Deduplicate URLs
    seen = set()
    unique = []
    for q in queries:
        if q["url"] not in seen:
            seen.add(q["url"])
            unique.append(q)

    logger.info("Generated %d unique LinkedIn queries (focus=%s)", len(unique), focus)
    return json.dumps({"queries": unique[:count], "total": len(unique)})


@tool
def get_search_keywords() -> str:
    """
    Get the user's configured search keywords, target roles, and technology preferences.
    Use this to understand what types of jobs to search for.
    """
    prefs = _load_preferences()
    return json.dumps({
        "roles": prefs["roles"],
        "keywords": prefs["keywords"],
        "exclude_roles": prefs["exclude_roles"],
        "exclude_keywords": prefs["exclude_keywords"],
        "experience_range": f"{prefs['min_experience_years']}-{prefs['experience_years']} years",
    })
