"""Key-free fallback keeps both search paths and policy-gated notifications."""

def test_career_company_rotation_is_bounded():
    from free_run import _career_companies

    config = {"target_companies": ["A", "B", "C", "D", "E"]}
    assert _career_companies(config, 2, day=1) == ["A", "B"]
    assert _career_companies(config, 2, day=2) == ["C", "D"]
    assert _career_companies(config, 2, day=3) == ["E", "A"]


def test_key_free_run_notifies_only_after_match(monkeypatch):
    import free_run
    from agent.middleware import BudgetTracker

    candidate = {
        "canonical_id": "linkedin:123456789", "source": "linkedin",
        "source_job_id": "123456789",
        "url": "https://www.linkedin.com/jobs/view/123456789",
        "title": "DevOps Engineer", "company": "Google", "location": "Bengaluru",
    }
    calls = []

    def fake_call(tool, args, budget):
        calls.append(tool.name)
        if tool.name == "fetch_job":
            return {"title": "DevOps Engineer", "company": "Google",
                    "location": "Bengaluru", "description": "Kubernetes and Terraform in India." * 10}
        if tool.name == "evaluate_job":
            return {"decision": "match", "score": 0.85, "confidence": 0.9,
                    "reasons": ["Relevant role"], "evaluation_mode": "deterministic"}
        if tool.name == "notify_user":
            return {"notified": True}
        return {"status": "recorded"}

    monkeypatch.setattr(free_run.JobRepository, "is_notified", lambda _: False)
    monkeypatch.setattr(free_run.JobRepository, "upsert", lambda *args: True)
    monkeypatch.setattr(free_run, "_call", fake_call)

    assert free_run._process(candidate, BudgetTracker()) is True
    assert calls == ["fetch_job", "evaluate_job", "record_decision", "notify_user"]


def test_key_free_run_skips_unrelated_titles_before_fetch(monkeypatch):
    import free_run
    from agent.middleware import BudgetTracker

    monkeypatch.setattr(free_run.JobRepository, "is_notified", lambda _: False)
    monkeypatch.setattr(free_run, "_call", lambda *args: (_ for _ in ()).throw(
        AssertionError("unrelated job should not be fetched")
    ))
    assert free_run._process({
        "canonical_id": "ats:1", "url": "https://example.com/job/1",
        "title": "Marketing Manager", "company": "Google",
    }, BudgetTracker()) is False


def test_linkedin_search_prefers_target_company_cards(monkeypatch):
    import json
    from types import SimpleNamespace
    from tools import search_tools

    html = """
    <div data-entity-urn="urn:li:jobPosting:123456789">
      <h3 class="base-search-card__title">Cloud Engineer</h3>
      <h4 class="base-search-card__subtitle">Other Company</h4>
      <span class="job-search-card__location">Bengaluru, India</span>
    </div>
    <div data-entity-urn="urn:li:jobPosting:987654321">
      <h3 class="base-search-card__title">Senior SRE</h3>
      <h4 class="base-search-card__subtitle">Visa</h4>
      <span class="job-search-card__location">Bengaluru, India</span>
    </div>
    """
    monkeypatch.setattr(search_tools, "_retry_get", lambda *args, **kwargs: SimpleNamespace(text=html))
    monkeypatch.setattr(search_tools, "_search_payload", lambda results, *_args, **_kwargs: json.dumps(results))
    results = json.loads(search_tools.search_linkedin.invoke({
        "url": "https://www.linkedin.com/jobs/search/", "max_results": 1,
    }))
    assert results[0]["company"] == "Visa"
    assert results[0]["title"] == "Senior SRE"
