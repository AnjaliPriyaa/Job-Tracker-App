"""
End-to-end test suite for the Company Tracking application.

Verifies imports, configuration, tools, and core logic.
"""

import os
import sys
from io import StringIO

print("=" * 70)
print("🧪 COMPANY TRACKING — END-TO-END TEST")
print("=" * 70)

passed = 0
failed = 0


# -----------------------------------------------------------------------
# Test 1: Module imports
# -----------------------------------------------------------------------
print("\n1️⃣ Testing imports...")
try:
    import utils
    import langchain_tools
    import langchain_ai
    import agent_app_simple
    print("   ✅ All modules imported successfully")
    passed += 1
except Exception as e:
    print(f"   ❌ Import failed: {e}")
    failed += 1
    sys.exit(1)


# -----------------------------------------------------------------------
# Test 2: Configuration
# -----------------------------------------------------------------------
print("\n2️⃣ Testing configuration...")
try:
    config = utils.load_config()
    assert config.get("experience_years") == 6, "experience_years should be 6"
    assert config.get("min_experience_years") == 4, "min_experience_years should be 4"
    assert len(config.get("target_companies", [])) > 0, "Should have target companies"
    assert len(config.get("exclude_roles", [])) > 0, "Should have excluded roles"
    print(f"   ✅ Config loaded: {len(config['target_companies'])} companies, "
          f"exp: {config['min_experience_years']}-{config['experience_years']} years")
    passed += 1
except Exception as e:
    print(f"   ❌ Config test failed: {e}")
    failed += 1


# -----------------------------------------------------------------------
# Test 3: Environment variables
# -----------------------------------------------------------------------
print("\n3️⃣ Testing environment...")
env_ok = True
if not os.getenv("GEMINI_API_KEY"):
    print("   ⚠️  GEMINI_API_KEY not set")
    env_ok = False
if not os.getenv("TELEGRAM_TOKEN"):
    print("   ⚠️  TELEGRAM_TOKEN not set")
    env_ok = False

if env_ok:
    print("   ✅ Environment variables configured")
else:
    print("   ⚠️  Some environment variables missing (optional for testing)")
passed += 1


# -----------------------------------------------------------------------
# Test 4: Utility functions
# -----------------------------------------------------------------------
print("\n4️⃣ Testing utility functions...")
try:
    # load_seen_jobs should return a set
    seen_jobs = utils.load_seen_jobs()
    assert isinstance(seen_jobs, set), "load_seen_jobs should return a set"

    # save_seen_jobs should persist
    test_jobs = {"4380358518", "4385241031"}
    utils.save_seen_jobs(test_jobs)
    reloaded = utils.load_seen_jobs()
    assert test_jobs.issubset(reloaded), "Saved jobs should be reloadable"

    # Restore original seen jobs
    utils.save_seen_jobs(seen_jobs)

    # check_and_cleanup should not crash
    utils.check_and_cleanup()

    # mark_job_seen / is_job_seen
    assert not utils.is_job_seen("9999999999"), "Unknown job should not be seen"
    utils.mark_job_seen("9999999999")
    assert utils.is_job_seen("9999999999"), "Job should now be seen"

    # Clean up test entry
    cleaned = utils.load_seen_jobs()
    cleaned.discard("9999999999")
    utils.save_seen_jobs(cleaned)

    print(f"   ✅ Utils working: {len(seen_jobs)} jobs tracked")
    passed += 1
except Exception as e:
    print(f"   ❌ Utils test failed: {e}")
    failed += 1


# -----------------------------------------------------------------------
# Test 5: LangChain tools
# -----------------------------------------------------------------------
print("\n5️⃣ Testing LangChain tools...")
try:
    tools = langchain_tools.ALL_TOOLS
    assert len(tools) == 6, f"Should have 6 tools, found {len(tools)}"
    tool_names = [t.name for t in tools]
    required = [
        "scrape_jobs",
        "get_job_description",
        "send_telegram",
        "manage_seen_jobs",
        "load_config",
        "filter_jobs_by_experience",
    ]
    for req in required:
        assert req in tool_names, f"Missing tool: {req}"
    print(f"   ✅ All {len(tools)} tools available: {', '.join(tool_names)}")
    passed += 1
except Exception as e:
    print(f"   ❌ Tools test failed: {e}")
    failed += 1


# -----------------------------------------------------------------------
# Test 6: Application initialization
# -----------------------------------------------------------------------
print("\n6️⃣ Testing application initialization...")
try:
    tracker = agent_app_simple.AgenticJobTracker()
    assert tracker.config is not None, "Config should be loaded"
    assert tracker.matcher is not None, "Matcher should be initialized"
    assert tracker.stats is not None, "Stats should be initialized"
    assert "started_at" in tracker.stats, "Stats should have started_at"
    mode = "AI enabled" if os.getenv("GEMINI_API_KEY") else "keyword-only mode"
    print(f"   ✅ AgenticJobTracker initialized successfully ({mode})")
    passed += 1
except Exception as e:
    print(f"   ❌ Initialization failed: {e}")
    import traceback; traceback.print_exc()
    failed += 1


# -----------------------------------------------------------------------
# Test 7: AI matcher (works with or without API key)
# -----------------------------------------------------------------------
print("\n7️⃣ Testing AI matcher initialization...")
try:
    matcher = langchain_ai.JobMatcher()
    assert matcher is not None, "JobMatcher should initialize"
    mode = "AI enabled" if os.getenv("GEMINI_API_KEY") else "keyword-only fallback"
    print(f"   ✅ JobMatcher initialized ({mode})")
    passed += 1
except Exception as e:
    print(f"   ❌ Matcher test failed: {e}")
    failed += 1


# -----------------------------------------------------------------------
# Test 8: Filtering logic (pure logic, no API)
# -----------------------------------------------------------------------
print("\n8️⃣ Testing filtering logic...")
try:
    from langchain_tools import filter_jobs_by_experience
    import json

    # Test: rejects high-experience requirement
    test_input = json.dumps({
        "jobs": [
            {"title": "Senior Engineer", "description": "Requires 8+ years of experience in DevOps"},
            {"title": "Junior Engineer", "description": "Looking for 1-2 years experience"},
        ],
        "my_experience": 5,
        "max_experience": 6,
    })
    result = json.loads(filter_jobs_by_experience.invoke({"input_data": test_input}))
    filtered = result.get("filtered_jobs", [])
    titles = [j["title"] for j in filtered]

    # The 8+ year job should be filtered out; junior should remain
    assert "Senior Engineer" not in titles, "Should reject 8+ years requirement"
    assert "Junior Engineer" in titles, "Should keep junior roles"
    print("   ✅ Experience filtering logic correct")
    passed += 1
except Exception as e:
    print(f"   ❌ Filtering test failed: {e}")
    import traceback; traceback.print_exc()
    failed += 1


# -----------------------------------------------------------------------
# Summary
# -----------------------------------------------------------------------
print("\n" + "=" * 70)
print("📊 TEST SUMMARY")
print("=" * 70)
print(f"   ✅ Passed: {passed}/8")
print(f"   ❌ Failed: {failed}/8")

if failed == 0:
    print("\n🎉 ALL TESTS PASSED!")
    print("\n✅ Application is ready to run:")
    print("   python agent_app_simple.py")
else:
    print(f"\n⚠️  {failed} test(s) failed")

print("=" * 70)
sys.exit(0 if failed == 0 else 1)
