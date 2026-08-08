"""Policy engine tests — deterministic validation rules."""

import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

DB_PATCH = patch('policies.job_policy.get_db')


def _mock_db_row(return_rows: list[dict]):
    """Create a mock DB that returns specified rows."""
    mock = MagicMock()
    # First call: jobs table, second: decisions, third: sources
    mock.execute.return_value.fetchone.side_effect = return_rows
    mock.execute.return_value.fetchall.return_value = []
    return mock


def test_policy_rejects_non_target_company():
    from policies.job_policy import PolicyEngine

    with DB_PATCH as mock_get_db:
        # Job exists, evaluated as MATCH with high confidence
        mock_db = _mock_db_row([
            {"canonical_id": "test:123"},  # job exists
            {"decision": "match", "confidence": 0.95},  # evaluated as match
        ])
        mock_db.execute.return_value.fetchall.return_value = []
        mock_get_db.return_value = mock_db

        engine = PolicyEngine.__new__(PolicyEngine)
        engine._config = {"target_companies": ["Google", "Microsoft"], "exclude_roles": [], "exclude_levels": []}
        engine.max_notifications_per_day = 20
        engine.min_confidence = 0.6

        with patch('policies.job_policy.JobRepository') as mock_repo, \
             patch('policies.job_policy.NotificationRepository') as mock_notif:
            mock_repo.is_notified.return_value = False
            mock_notif.count_today.return_value = 0
            result = engine.validate_notification("test:123", "Accenture", "DevOps Engineer")
            assert not result.allowed
            assert "not in target list" in result.reason


def test_policy_allows_valid_job():
    from policies.job_policy import PolicyEngine

    with DB_PATCH as mock_get_db:
        mock_db = _mock_db_row([
            {"canonical_id": "test:123"},
            {"decision": "match", "confidence": 0.95},
        ])
        mock_db.execute.return_value.fetchall.return_value = [{"location": "Bengaluru", "description": "DevOps role"}]
        mock_get_db.return_value = mock_db

        engine = PolicyEngine.__new__(PolicyEngine)
        engine._config = {"target_companies": ["Google"], "exclude_roles": [], "exclude_levels": []}
        engine.max_notifications_per_day = 20
        engine.min_confidence = 0.6

        with patch('policies.job_policy.JobRepository') as mock_repo, \
             patch('policies.job_policy.NotificationRepository') as mock_notif:
            mock_repo.is_notified.return_value = False
            mock_notif.count_today.return_value = 0
            result = engine.validate_notification("test:123", "Google", "DevOps Engineer")
            assert result.allowed, f"Expected allowed, got: {result.reason}"


def test_policy_rejects_job_not_found():
    from policies.job_policy import PolicyEngine

    with DB_PATCH as mock_get_db:
        mock_db = _mock_db_row([None, None])  # job not found
        mock_get_db.return_value = mock_db

        engine = PolicyEngine.__new__(PolicyEngine)
        engine._config = {"target_companies": ["Google"], "exclude_roles": [], "exclude_levels": []}
        engine.max_notifications_per_day = 20
        engine.min_confidence = 0.6

        result = engine.validate_notification("test:nonexistent", "Google", "DevOps")
        assert not result.allowed
        assert "not found" in result.reason


def test_policy_rejects_not_evaluated():
    from policies.job_policy import PolicyEngine

    with DB_PATCH as mock_get_db:
        mock_db = _mock_db_row([
            {"canonical_id": "test:123"},
            None,  # no decision
        ])
        mock_get_db.return_value = mock_db

        engine = PolicyEngine.__new__(PolicyEngine)
        engine._config = {"target_companies": ["Google"], "exclude_roles": [], "exclude_levels": []}
        engine.max_notifications_per_day = 20
        engine.min_confidence = 0.6

        result = engine.validate_notification("test:123", "Google", "DevOps")
        assert not result.allowed
        assert "not been evaluated" in result.reason


def test_policy_rejects_low_confidence():
    from policies.job_policy import PolicyEngine

    with DB_PATCH as mock_get_db:
        mock_db = _mock_db_row([
            {"canonical_id": "test:123"},
            {"decision": "match", "confidence": 0.3},  # below threshold
        ])
        mock_get_db.return_value = mock_db

        engine = PolicyEngine.__new__(PolicyEngine)
        engine._config = {"target_companies": ["Google"], "exclude_roles": [], "exclude_levels": []}
        engine.max_notifications_per_day = 20
        engine.min_confidence = 0.6

        result = engine.validate_notification("test:123", "Google", "DevOps")
        assert not result.allowed
        assert "confidence" in result.reason.lower()


def test_policy_rejects_excluded_role():
    from policies.job_policy import PolicyEngine

    with DB_PATCH as mock_get_db:
        mock_db = _mock_db_row([
            {"canonical_id": "test:123"},
            {"decision": "match", "confidence": 0.95},
        ])
        mock_db.execute.return_value.fetchall.return_value = [{"location": "Bengaluru", "description": ""}]
        mock_get_db.return_value = mock_db

        engine = PolicyEngine.__new__(PolicyEngine)
        engine._config = {"target_companies": ["Google"], "exclude_roles": ["manager"], "exclude_levels": []}
        engine.max_notifications_per_day = 20
        engine.min_confidence = 0.6

        with patch('policies.job_policy.JobRepository') as mock_repo, \
             patch('policies.job_policy.NotificationRepository') as mock_notif:
            mock_repo.is_notified.return_value = False
            mock_notif.count_today.return_value = 0
            result = engine.validate_notification("test:123", "Google", "Engineering Manager")
            assert not result.allowed
            assert "manager" in result.reason.lower()


def test_policy_rejects_duplicate():
    from policies.job_policy import PolicyEngine

    with DB_PATCH as mock_get_db:
        mock_db = _mock_db_row([
            {"canonical_id": "test:123"},
            {"decision": "match", "confidence": 0.95},
        ])
        mock_db.execute.return_value.fetchall.return_value = [{"location": "Bengaluru", "description": ""}]
        mock_get_db.return_value = mock_db

        engine = PolicyEngine.__new__(PolicyEngine)
        engine._config = {"target_companies": ["Google"], "exclude_roles": [], "exclude_levels": []}
        engine.max_notifications_per_day = 20
        engine.min_confidence = 0.6

        with patch('policies.job_policy.JobRepository') as mock_repo, \
             patch('policies.job_policy.NotificationRepository') as mock_notif:
            mock_repo.is_notified.return_value = True
            mock_notif.count_today.return_value = 0
            result = engine.validate_notification("test:123", "Google", "SRE")
            assert not result.allowed
            assert "already notified" in result.reason.lower()


def test_location_reject():
    from policies.job_policy import PolicyEngine
    engine = PolicyEngine.__new__(PolicyEngine)
    engine._config = {}
    assert not engine.is_valid_location("Job in San Francisco, CA")
    assert not engine.is_valid_location("London, UK based role")
    assert not engine.is_valid_location("Remote, US")


def test_location_accept():
    from policies.job_policy import PolicyEngine
    engine = PolicyEngine.__new__(PolicyEngine)
    engine._config = {}
    assert engine.is_valid_location("Job in Bengaluru, Karnataka")
    assert engine.is_valid_location("Hyderabad based role")
    assert engine.is_valid_location("Remote position")
