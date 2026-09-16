"""Regression tests for the cost controls around the agent loop."""

import json
from pathlib import Path
from types import SimpleNamespace

from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, LLMResult


def test_budget_reads_real_tool_name_and_enforces_search_limit():
    from agent.middleware import BudgetMiddleware, BudgetTracker

    budget = BudgetTracker(max_tool_calls=5, max_searches=1)
    middleware = BudgetMiddleware(budget)
    request = SimpleNamespace(tool_call={"name": "search_linkedin", "id": "call-1"})

    assert middleware.wrap_tool_call(request, lambda _: "ok") == "ok"
    blocked_message = middleware.wrap_tool_call(request, lambda _: "unexpected")
    blocked = json.loads(blocked_message.content)

    assert blocked["blocked"] is True
    assert blocked_message.status == "error"
    assert budget.searches == 2
    assert budget.tool_call_counts["search_linkedin"] == 2


def test_obvious_reject_never_calls_matcher(monkeypatch):
    import tools.evaluation_tools as evaluation
    from agent.middleware import set_budget

    set_budget(None)
    monkeypatch.setattr(
        evaluation,
        "_get_matcher",
        lambda: (_ for _ in ()).throw(AssertionError("matcher should not be called")),
    )
    result = json.loads(evaluation.evaluate_job.invoke({
        "title": "Senior DevOps Engineer",
        "company": "Google",
        "location": "Bengaluru, India",
        "description": "This role requires 8+ years of Kubernetes and Terraform experience. " * 3,
    }))

    assert result["decision"] == "reject"
    assert result["evaluation_mode"] == "deterministic"


def test_strong_match_never_calls_matcher(monkeypatch):
    import tools.evaluation_tools as evaluation
    from agent.middleware import set_budget

    set_budget(None)
    monkeypatch.setattr(
        evaluation,
        "_get_matcher",
        lambda: (_ for _ in ()).throw(AssertionError("matcher should not be called")),
    )
    result = json.loads(evaluation.evaluate_job.invoke({
        "title": "DevOps Engineer",
        "company": "Google",
        "location": "Bengaluru, India",
        "description": (
            "Build Kubernetes platforms with Terraform and AWS. Work with CI/CD, "
            "Linux, monitoring, and automation in India. Requires 5+ years of experience."
        ),
    }))

    assert result["decision"] == "match"
    assert result["evaluation_mode"] == "deterministic"


def test_ambiguous_job_uses_one_bounded_matcher_call(monkeypatch):
    import tools.evaluation_tools as evaluation
    from agent.middleware import set_budget
    from models.decisions import Decision, EvaluationResult

    class FakeMatcher:
        calls = 0

        def invoke(self, prompt, config=None):
            self.calls += 1
            assert len(prompt) < 2500
            assert config == {"tags": ["evaluation"]}
            return EvaluationResult(
                decision=Decision.INVESTIGATE,
                score=0.5,
                confidence=0.7,
                reasons=["Ambiguous title"],
            )

    matcher = FakeMatcher()
    set_budget(None)
    monkeypatch.setattr(evaluation, "_get_matcher", lambda: matcher)
    result = json.loads(evaluation.evaluate_job.invoke({
        "title": "Production Engineer",
        "company": "Google",
        "location": "Bengaluru, India",
        "description": (
            "Operate production systems and automate Kubernetes services. "
            "Collaborate with engineering teams on reliability and incident response. "
            "Four years of relevant experience is preferred."
        ),
    }))

    assert matcher.calls == 1
    assert result["evaluation_mode"] == "llm"


def test_cross_source_linkedin_duplicates_are_removed(monkeypatch):
    import tools.search_tools as search

    class FakeRepository:
        jobs = set()
        sources = {}
        urls = {}

        @classmethod
        def find_by_source(cls, source, source_job_id):
            return cls.sources.get((source, source_job_id))

        @classmethod
        def find(cls, canonical_id):
            return canonical_id if canonical_id in cls.jobs else None

        @classmethod
        def find_by_url(cls, url):
            return cls.urls.get(url)

        @classmethod
        def find_by_secondary(cls, company, title, location):
            return None

        @classmethod
        def upsert(cls, canonical_id, company, title, location, source,
                   source_job_id, url, description=""):
            is_new = canonical_id not in cls.jobs
            cls.jobs.add(canonical_id)
            cls.sources[(source, source_job_id)] = canonical_id
            cls.urls[url] = canonical_id
            return is_new

    monkeypatch.setattr(search, "JobRepository", FakeRepository)
    first, first_duplicates = search._deduplicate_and_store([{
        "source": "google_jobs",
        "source_job_id": "123456789",
        "url": "https://www.linkedin.com/jobs/view/123456789",
        "title": "DevOps Engineer",
    }], 10)
    second, second_duplicates = search._deduplicate_and_store([{
        "source": "linkedin",
        "source_job_id": "123456789",
        "url": "https://www.linkedin.com/jobs/view/123456789",
        "title": "DevOps Engineer",
    }], 10)

    assert first[0]["canonical_id"] == "linkedin:123456789"
    assert first_duplicates == 0
    assert second == []
    assert second_duplicates == 1


def test_token_usage_tracker_counts_nested_evaluation():
    from agent.stats import TokenUsageTracker

    tracker = TokenUsageTracker()
    response = LLMResult(generations=[[ChatGeneration(message=AIMessage(
        content="done",
        usage_metadata={
            "input_tokens": 100,
            "output_tokens": 20,
            "total_tokens": 120,
            "input_token_details": {"cache_read": 40},
        },
        response_metadata={"model_name": "deepseek-chat"},
    ))]])
    tracker.on_llm_end(response, tags=["evaluation"])

    assert tracker.summary() == {
        "llm_calls": 1,
        "evaluation_llm_calls": 1,
        "input_tokens": 100,
        "output_tokens": 20,
        "total_tokens": 120,
        "cached_input_tokens": 40,
        "calls_by_model": {"deepseek-chat": 1},
    }


def test_agent_uses_bounded_single_agent_harness():
    source = (Path(__file__).resolve().parent.parent / "agent.py").read_text()
    assert "create_deep_agent" not in source
    assert "ModelCallLimitMiddleware" in source
    assert "ContextEditingMiddleware" in source


def test_gemini_requires_explicit_deepseek_opt_in(monkeypatch):
    import importlib.util

    entrypoint = Path(__file__).resolve().parent.parent / "agent.py"
    spec = importlib.util.spec_from_file_location("job_tracker_entrypoint", entrypoint)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    monkeypatch.setenv("GEMINI_API_KEY", "test-gemini-key")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-deepseek-key")
    monkeypatch.delenv("AI_PROVIDER", raising=False)
    assert module._selected_provider() == "gemini"

    monkeypatch.setenv("AI_PROVIDER", "deepseek")
    assert module._selected_provider() == "deepseek"


def test_gemini_never_starts_nested_deepseek_evaluation(monkeypatch):
    import tools.evaluation_tools as evaluation

    monkeypatch.setenv("AI_PROVIDER", "gemini")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-deepseek-key")
    monkeypatch.setattr(evaluation, "_matcher", None)
    assert evaluation._get_matcher() == "fallback"
