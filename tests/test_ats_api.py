"""Public career-board API regressions; no network calls in these tests."""

import json


class FakeResponse:
    status_code = 200

    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


def test_greenhouse_api_extracts_description_and_location(monkeypatch):
    from tools import ats_parsers

    def fake_get(url, **kwargs):
        assert url == "https://boards-api.greenhouse.io/v1/boards/example/jobs?content=true"
        return FakeResponse({"jobs": [{
            "id": 123, "title": "DevOps Engineer",
            "absolute_url": "https://example.com/jobs/123",
            "location": {"name": "Bengaluru, India"},
            "content": "<p>Kubernetes and Terraform</p>",
        }]})

    monkeypatch.setattr(ats_parsers.requests, "get", fake_get)
    jobs = ats_parsers.parse_greenhouse("https://boards.greenhouse.io/example", "Example")
    assert jobs[0]["source_job_id"] == "greenhouse_123"
    assert jobs[0]["location"] == "Bengaluru, India"
    assert jobs[0]["description"] == "Kubernetes and Terraform"


def test_ashby_api_ignores_unlisted_jobs(monkeypatch):
    from tools import ats_parsers

    monkeypatch.setattr(ats_parsers.requests, "get", lambda *args, **kwargs: FakeResponse({
        "jobs": [
            {"id": "visible", "title": "Platform Engineer", "jobUrl": "https://jobs.ashbyhq.com/example/visible",
             "location": "Hyderabad, India", "descriptionPlain": "Kubernetes and AWS", "isListed": True},
            {"id": "hidden", "title": "Platform Engineer", "jobUrl": "https://jobs.ashbyhq.com/example/hidden",
             "isListed": False},
        ],
    }))
    jobs = ats_parsers.parse_ashby("https://jobs.ashbyhq.com/example", "Example")
    assert len(jobs) == 1
    assert jobs[0]["source_job_id"] == "ashby_visible"


def test_ats_search_prioritizes_relevant_india_roles(monkeypatch):
    from tools import ats_parsers, search_tools

    postings = [
        {"source_job_id": "1", "url": "https://example.com/1", "title": "Designer", "location": "India"},
        {"source_job_id": "2", "url": "https://example.com/2", "title": "Platform Engineer", "location": "US"},
        {"source_job_id": "3", "url": "https://example.com/3", "title": "DevOps Engineer", "location": "Bengaluru, India"},
    ]
    monkeypatch.setattr(ats_parsers, "parse_ats", lambda *args: postings)
    monkeypatch.setattr(search_tools, "_search_payload", lambda results, *_args, **_kwargs: json.dumps(results))
    result = json.loads(search_tools.search_ats.invoke({
        "company": "Example", "ats_url": "https://boards.greenhouse.io/example", "max_results": 1,
    }))
    assert result[0]["title"] == "DevOps Engineer"
