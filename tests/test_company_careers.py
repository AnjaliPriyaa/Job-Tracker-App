"""Verified company-domain search; no live requests or job-board fallback."""

import json
from types import SimpleNamespace
from pathlib import Path

import pytest


def test_apple_first_party_jobs_use_full_official_detail(monkeypatch):
    from tools import company_careers

    listing = """
    <li class="rc-accordion-item">
      <h3><a href="/en-in/details/123/site-reliability-engineer?team=SFTWR">Site Reliability Engineer</a></h3>
      <div class="job-title-location">Location Bengaluru</div>
      <div class="job-list-item pb-30">Short job preview</div>
    </li>
    <li class="rc-accordion-item">
      <h3><a href="/en-in/details/456/engineering-manager">SRE Engineering Manager</a></h3>
      <div class="job-title-location">Location Bengaluru</div>
    </li>
    """
    data = {"loaderData": {"jobDetails": {"jobsData": {
        "postingTitle": "Site Reliability Engineer",
        "selectedLocation": {"city": "Bengaluru", "stateProvince": "Karnataka",
                             "countryName": "India"},
        "minimumQualifications": "6+ years in SRE with Kubernetes.",
        "description": "Operate reliable cloud infrastructure with Terraform and Python.",
        "jobSummary": "Join the infrastructure team.",
    }}}}
    detail = f'<script>window.__staticRouterHydrationData = JSON.parse({json.dumps(json.dumps(data))});</script>'
    requested = []

    def fake_get(url, hosts):
        requested.append(url)
        assert hosts == ["jobs.apple.com"]
        return detail if "/details/" in url else listing

    monkeypatch.setattr(company_careers, "_get_page", fake_get)
    jobs = company_careers.first_party_jobs("Apple", {
        "allowed_hosts": ["jobs.apple.com"],
        "pages": ["https://jobs.apple.com/en-in/search?location=bengaluru-BGS"],
    }, 4)
    assert len(jobs) == 1
    assert jobs[0]["url"].startswith("https://jobs.apple.com/en-in/details/123/")
    assert jobs[0]["location"] == "Bengaluru, Karnataka, India"
    assert jobs[0]["description"].startswith("6+ years")
    assert jobs[0]["source"] == "company_career"
    assert len(requested) == 2


def test_microsoft_first_party_job_is_not_an_ats_listing(monkeypatch):
    from tools import company_careers

    html = """
    <div class="careers-joblistResponsive-columnList">
      <h3 class="careers-joblistResponsive-subheading">Cloud Engineer</h3>
      <div class="careers-joblistResponsive-primarylocation">India, Telangana, Hyderabad</div>
      <div class="careers-joblistResponsive-desc">Kubernetes, Terraform, Azure and Python infrastructure.</div>
      <a href="https://apply.careers.microsoft.com/careers/job/123">See details</a>
    </div>
    <div class="careers-joblistResponsive-columnList">
      <h3 class="careers-joblistResponsive-subheading">Cloud Engineer</h3>
      <div class="careers-joblistResponsive-primarylocation">Seattle, US</div>
      <a href="https://apply.careers.microsoft.com/careers/job/456">See details</a>
    </div>
    """
    monkeypatch.setattr(company_careers, "_get_page", lambda *args: html)
    jobs = company_careers.first_party_jobs("Microsoft", {
        "allowed_hosts": ["careers.microsoft.com", "apply.careers.microsoft.com"],
        "pages": ["https://careers.microsoft.com/v2/global/en/locations/hyderabad.html"],
    }, 4)
    assert len(jobs) == 1
    assert jobs[0]["url"] == "https://apply.careers.microsoft.com/careers/job/123"
    assert jobs[0]["location"] == "India, Telangana, Hyderabad"


def test_google_first_party_card_uses_official_detail_and_deduplicates(monkeypatch):
    from tools import company_careers

    listing = '''
    <li class="lLd3Je">
      <h3>Site Reliability Engineer</h3>
      <span class="r0wTof">Bengaluru, Karnataka, India</span>
      <div class="Xsxa1e">Minimum qualifications: Python and Linux</div>
      <a href="jobs/results/123-site-reliability-engineer?location=Bengaluru">Learn more</a>
    </li>'''
    detail = '''
    <div><h3>Minimum qualifications:</h3><ul><li>5 years of Linux experience.</li></ul></div>
    <div class="aG5W3"><h3>About the job</h3>Build Kubernetes infrastructure.</div>
    <div class="BDNOWe"><h3>Responsibilities</h3>Operate services with Terraform.</div>
    '''
    requested = []

    def fake_get(url, hosts):
        requested.append(url)
        return detail if "123-site-reliability-engineer" in url else listing

    monkeypatch.setattr(company_careers, "_get_page", fake_get)
    jobs = company_careers.first_party_jobs("Google", {
        "allowed_hosts": ["www.google.com"],
        "pages": [
            "https://www.google.com/about/careers/applications/jobs/results/?q=sre",
            "https://www.google.com/about/careers/applications/jobs/results/?q=platform",
        ],
    }, 4)
    assert len(jobs) == 1
    assert jobs[0]["url"].startswith(
        "https://www.google.com/about/careers/applications/jobs/results/123-"
    )
    assert jobs[0]["description"].startswith("5 years of Linux experience.")
    assert len(requested) == 3


def test_company_redirect_to_external_board_is_rejected(monkeypatch):
    from tools import company_careers

    calls = []

    def fake_get(url, **kwargs):
        calls.append(url)
        return SimpleNamespace(status_code=302, headers={
            "Location": "https://boards.greenhouse.io/example"
        })

    monkeypatch.setattr(company_careers.requests, "get", fake_get)
    with pytest.raises(ValueError, match="Not a verified company-owned URL"):
        company_careers._get_page("https://careers.example.com/jobs", ["careers.example.com"])
    assert calls == ["https://careers.example.com/jobs"]


def test_jsonld_fallback_requires_real_jobposting():
    from tools.company_careers import _jsonld_listings

    html = '''<script type="application/ld+json">{
      "@context":"https://schema.org", "@type":"JobPosting",
      "title":"Platform Engineer", "url":"https://careers.example.com/jobs/123",
      "jobLocation":{"address":{"addressLocality":"Bengaluru","addressCountry":"India"}},
      "description":"<p>Build Kubernetes platforms.</p>"
    }</script>'''
    jobs = _jsonld_listings(html)
    assert jobs[0]["title"] == "Platform Engineer"
    assert jobs[0]["location"] == "Bengaluru, India"
    assert jobs[0]["description"] == "Build Kubernetes platforms."


def test_search_tool_returns_only_verified_company_results(monkeypatch):
    from tools import company_careers, search_tools

    monkeypatch.setattr(company_careers, "first_party_jobs", lambda *_args: [{
        "source": "company_career", "source_job_id": "apple:/en-in/details/123",
        "url": "https://jobs.apple.com/en-in/details/123/site-reliability-engineer",
        "title": "Site Reliability Engineer", "location": "Bengaluru, India",
        "description": "Kubernetes and Terraform in a site reliability role.",
    }])
    monkeypatch.setattr(search_tools, "_search_payload",
                        lambda results, *_args, **_kwargs: json.dumps(results))
    result = json.loads(search_tools.search_company_careers.invoke({
        "company": "Apple", "max_results": 2,
    }))
    assert result[0]["source"] == "company_career"
    assert result[0]["company"] == "Apple"


def test_knowledge_base_covers_every_target_without_ats_hosts():
    root = Path(__file__).resolve().parent.parent
    config = json.loads((root / "config.json").read_text())
    knowledge = json.loads((root / "career_knowledge.json").read_text())
    assert set(knowledge) == set(config["target_companies"])
    assert len(knowledge) == 90
    assert all("/" not in domain and not domain.startswith("boards.")
               for domain in knowledge.values())


def test_generic_skill_follows_first_party_role_and_requires_live_detail(monkeypatch):
    from tools import company_careers

    landing = '''
      <a href="/careers/jobs">Browse jobs</a>
      <a href="https://boards.greenhouse.io/example">Site Reliability Engineer</a>
    '''
    listings = '''
      <article><a href="/careers/jobs/123-site-reliability-engineer">Site Reliability Engineer</a>
      Bengaluru, India</article>
      <a href="/careers/jobs/456-marketing-manager">Marketing Manager</a>
    '''
    detail = '''<html><head><script type="application/ld+json">{
      "@context":"https://schema.org", "@type":"JobPosting",
      "title":"Site Reliability Engineer",
      "url":"https://example.com/careers/jobs/123-site-reliability-engineer",
      "jobLocation":{"address":{"addressLocality":"Bengaluru", "addressCountry":"India"}},
      "description":"Build and operate Kubernetes and Terraform platforms in Bengaluru. Improve reliability, automate deployment pipelines, respond to incidents, and collaborate with product engineering teams."
    }</script></head></html>'''
    requested = []

    def fake_get(url, hosts):
        requested.append(url)
        if url.endswith("/123-site-reliability-engineer"):
            return detail
        if url.endswith("/careers/jobs"):
            return listings
        return landing

    monkeypatch.setattr(company_careers, "_get_page", fake_get)
    jobs = company_careers.first_party_jobs("Example", {
        "strategy": "generic", "allowed_hosts": ["example.com", ".example.com"],
        "pages": ["https://example.com/careers"],
    }, 2)
    assert len(jobs) == 1
    assert jobs[0]["source"] == "company_career"
    assert jobs[0]["location"] == "Bengaluru, India"
    assert all("greenhouse" not in url for url in requested)


def test_generic_skill_rejects_closed_job(monkeypatch):
    from tools import company_careers

    landing = '<a href="/careers/jobs/123-cloud-engineer">Cloud Engineer</a>'
    closed = '''<main><h1>Cloud Engineer</h1>Bengaluru, India.
    This job has been filled. Kubernetes Terraform Python operations and cloud infrastructure.
    We need an engineer to work on systems with several teams across the company.</main>'''
    monkeypatch.setattr(company_careers, "_get_page", lambda url, hosts: (
        closed if "/123-cloud-engineer" in url else landing
    ))
    assert company_careers.first_party_jobs("Example", {
        "strategy": "generic", "allowed_hosts": ["example.com"],
        "pages": ["https://example.com/careers"],
    }, 2) == []


def test_generic_skill_rejects_expired_structured_job():
    from tools.company_careers import _generic_detail

    html = '''<script type="application/ld+json">{
      "@type":"JobPosting", "title":"Cloud Engineer",
      "validThrough":"2020-01-01T00:00:00Z",
      "jobLocation":{"address":{"addressLocality":"Bengaluru", "addressCountry":"India"}},
      "description":"Build Kubernetes and Terraform platforms for teams in Bengaluru."
    }</script>'''
    assert _generic_detail(html, "https://careers.example.com/jobs/123") == {}


def test_generic_skill_rejects_noncompany_redirect(monkeypatch):
    from tools import company_careers

    monkeypatch.setattr(company_careers.requests, "get", lambda *_args, **_kwargs:
                        SimpleNamespace(status_code=302, headers={
                            "Location": "https://jobs.lever.co/example"
                        }))
    with pytest.raises(ValueError, match="Not a verified company-owned URL"):
        company_careers._get_page("https://careers.example.com/jobs", [".example.com"])
