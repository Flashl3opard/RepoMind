import pytest

from app.api.dashboard_auth import DashboardAuthConfigError, is_authorized, validate_auth_config
from app.config import Settings


def make_settings(**kwargs) -> Settings:
    return Settings(**kwargs)


# -- is_authorized --------------------------------------------------------------------------


def test_authorized_with_correct_bearer_token():
    settings = make_settings(DASHBOARD_API_KEY="secret123")
    assert is_authorized("Bearer secret123", settings)


def test_unauthorized_with_wrong_bearer_token():
    settings = make_settings(DASHBOARD_API_KEY="secret123")
    assert not is_authorized("Bearer wrong", settings)


def test_unauthorized_with_missing_header():
    settings = make_settings(DASHBOARD_API_KEY="secret123")
    assert not is_authorized(None, settings)


def test_bearer_prefix_is_required_exactly():
    settings = make_settings(DASHBOARD_API_KEY="secret123")
    assert not is_authorized("secret123", settings)  # missing "Bearer " prefix
    assert not is_authorized("bearer secret123", settings)  # wrong case


# -- validate_auth_config -------------------------------------------------------------------


def test_validate_auth_config_warns_but_does_not_raise_when_key_unset(caplog):
    settings = make_settings(DASHBOARD_API_KEY=None, DASHBOARD_AUTH_DISABLED=False)
    validate_auth_config(settings)  # must not raise -- fail-closed happens per-request, not at startup
    assert "DASHBOARD_API_KEY is not set" in caplog.text


def test_validate_auth_config_allows_configured_key():
    settings = make_settings(DASHBOARD_API_KEY="secret123", DASHBOARD_AUTH_DISABLED=False)
    validate_auth_config(settings)


def test_validate_auth_config_allows_auth_disabled_with_safe_defaults(caplog):
    settings = make_settings(DASHBOARD_AUTH_DISABLED=True, REVIEW_DRY_RUN=True, GITHUB_WEBHOOK_SECRET=None)
    validate_auth_config(settings)
    assert "DASHBOARD_AUTH_DISABLED=true" in caplog.text


def test_validate_auth_config_rejects_auth_disabled_with_dry_run_false():
    settings = make_settings(DASHBOARD_AUTH_DISABLED=True, REVIEW_DRY_RUN=False, GITHUB_WEBHOOK_SECRET=None)
    with pytest.raises(DashboardAuthConfigError, match="REVIEW_DRY_RUN"):
        validate_auth_config(settings)


def test_validate_auth_config_rejects_auth_disabled_with_webhook_secret_set():
    settings = make_settings(DASHBOARD_AUTH_DISABLED=True, REVIEW_DRY_RUN=True, GITHUB_WEBHOOK_SECRET="shh")
    with pytest.raises(DashboardAuthConfigError, match="GITHUB_WEBHOOK_SECRET"):
        validate_auth_config(settings)
