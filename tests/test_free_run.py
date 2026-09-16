"""Key-free fallback keeps both search paths and policy-gated notifications."""

def test_career_company_rotation_is_bounded():
    from free_run import _career_companies

    config = {"target_companies": ["A", "B", "C", "D", "E"]}
    assert _career_companies(config, 2, day=1) == ["A", "B"]
    assert _career_companies(config, 2, day=2) == ["C", "D"]
    assert _career_companies(config, 2, day=3) == ["E", "A"]


def test_first_party_company_pool_uses_available_knowledge():
    from free_run import _career_companies

    config = {"target_companies": ["Apple", "Google", "Microsoft"]}
    assert _career_companies(config, 6, day=1, available={"Apple", "Microsoft"}) == [
        "Apple", "Microsoft",
    ]


def test_career_source_memory_prefers_unsearched_companies(monkeypatch):
    from free_run import _career_companies

    monkeypatch.setenv("FREE_CAREER_PRIORITY", "Apple")
    config = {"target_companies": ["Apple", "Google", "Microsoft", "Adobe"]}
    assert _career_companies(config, 3, available=set(config["target_companies"]),
                             last_attempted={"Google": "2026-09-16T00:00:00+00:00"}) == [
        "Apple", "Microsoft", "Adobe",
    ]


def test_career_run_does_not_fall_back_to_ats(monkeypatch):
    import free_run
    from agent.middleware import BudgetTracker

    monkeypatch.setenv("FREE_CAREER_PRIORITY", "Apple")
    monkeypatch.setenv("FREE_MAX_COMPANIES", "1")
    calls = []

    def fake_call(tool, args, budget):
        calls.append(tool.name)
        assert tool.name == "search_company_careers"
        return {"results": [{"canonical_id": "company_career:apple:1"}],
                "new_count": 1, "duplicates_filtered": 0, "error": None}

    monkeypatch.setattr(free_run, "_call", fake_call)
    monkeypatch.setattr(free_run, "_career_attempts", lambda: {})
    monkeypatch.setattr(free_run, "_remember_career_source", lambda *_args: None)
    result = free_run._discover("career", {
        "target_companies": ["Apple", "Notion"],
        "company_career_pages": {"Apple": {"pages": ["https://jobs.apple.com"]}},
    }, BudgetTracker(), 12)
    assert result[0]["canonical_id"] == "company_career:apple:1"
    assert calls == ["search_company_careers"]


def test_pending_retries_matched_jobs_after_notification_was_blocked(monkeypatch):
    import free_run

    class FakeDb:
        def execute(self, query, params):
            assert "'match'" in query
            assert "CASE WHEN j.status = 'match' THEN 0" in query
            assert params == ("linkedin", 12)
            return self

        def fetchall(self):
            return [{"canonical_id": "linkedin:4463332504", "source": "linkedin",
                     "source_job_id": "4463332504", "url": "https://www.linkedin.com/jobs/view/4463332504",
                     "title": "Senior SRE", "company": "Visa", "location": "Bengaluru"}]

    monkeypatch.setattr(free_run, "get_db", lambda: FakeDb())
    assert free_run._pending("linkedin", 12)[0]["canonical_id"] == "linkedin:4463332504"


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
