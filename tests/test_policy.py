"""Policy engine tests — verify deterministic validation rules."""

import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Mock DB calls that PolicyEngine.validate_notification() depends on
DB_PATCH = patch('policies.job_policy.JobRepository.is_notified', return_value=False)
NOTIF_PATCH = patch('policies.job_policy.NotificationRepository.count_today', return_value=0)


def _make_engine(config: dict):
    """Create a PolicyEngine with custom config."""
    from policies.job_policy import PolicyEngine
    engine = PolicyEngine.__new__(PolicyEngine)
    engine._config = config
    engine.max_notifications_per_day = 20
    engine.min_confidence = 0.6
    return engine


def test_policy_rejects_non_target_company():
    """Policy should reject companies not in target list."""
    with DB_PATCH, NOTIF_PATCH:
        engine = _make_engine({
            "target_companies": ["Google", "Microsoft", "Stripe"],
            "exclude_roles": ["manager", "lead"],
            "exclude_levels": ["junior", "intern"],
        })
        result = engine.validate_notification("test:123", "Accenture", "DevOps Engineer")
        assert not result.allowed
        assert "not in target list" in result.reason


def test_policy_allows_target_company():
    """Policy should allow companies in target list."""
    with DB_PATCH, NOTIF_PATCH:
        engine = _make_engine({
            "target_companies": ["Google", "Microsoft", "Stripe"],
            "exclude_roles": ["manager", "lead"],
            "exclude_levels": ["junior", "intern"],
        })
        result = engine.validate_notification("test:123", "Google", "DevOps Engineer")
        assert result.allowed, f"Expected allowed, got: {result.reason}"


def test_policy_rejects_excluded_role():
    """Policy should reject titles containing excluded roles."""
    with DB_PATCH, NOTIF_PATCH:
        engine = _make_engine({
            "target_companies": ["Google", "Microsoft"],
            "exclude_roles": ["manager", "lead", "architect"],
            "exclude_levels": ["junior", "intern"],
        })
        result = engine.validate_notification("test:123", "Google", "Engineering Manager")
        assert not result.allowed
        assert "manager" in result.reason.lower()


def test_policy_rejects_duplicate():
    """Policy should reject already-notified jobs."""
    with patch('policies.job_policy.JobRepository.is_notified', return_value=True), NOTIF_PATCH:
        engine = _make_engine({
            "target_companies": ["Google"],
            "exclude_roles": [],
            "exclude_levels": [],
        })
        result = engine.validate_notification("test:123", "Google", "SRE")
        assert not result.allowed
        assert "already notified" in result.reason.lower()


def test_location_reject():
    """Should reject non-India locations."""
    engine = _make_engine({})
    assert not engine.is_valid_location("Job in San Francisco, CA")
    assert not engine.is_valid_location("London, UK based role")
    assert not engine.is_valid_location("Remote, US")
    assert not engine.is_valid_location("Position in New York, NY")


def test_location_accept():
    """Should accept India locations."""
    engine = _make_engine({})
    assert engine.is_valid_location("Job in Bengaluru, Karnataka")
    assert engine.is_valid_location("Hyderabad based role")
    assert engine.is_valid_location("Remote position anywhere in India")
    assert engine.is_valid_location("Remote")
