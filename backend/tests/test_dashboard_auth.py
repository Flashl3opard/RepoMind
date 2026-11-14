from app.api.dashboard_auth import is_authorized
from app.config import Settings


def make_settings(api_key=None) -> Settings:
    return Settings(DASHBOARD_API_KEY=api_key)


def test_authorized_with_correct_bearer_token():
    settings = make_settings(api_key="secret123")
    assert is_authorized("Bearer secret123", "1.2.3.4", settings)


def test_unauthorized_with_wrong_bearer_token():
    settings = make_settings(api_key="secret123")
    assert not is_authorized("Bearer wrong", "1.2.3.4", settings)


def test_unauthorized_with_missing_header_when_key_configured():
    settings = make_settings(api_key="secret123")
    assert not is_authorized(None, "127.0.0.1", settings)


def test_localhost_always_fails_without_header_if_key_is_set():
    # a configured key means the key is required everywhere, localhost included
    settings = make_settings(api_key="secret123")
    assert not is_authorized(None, "127.0.0.1", settings)


def test_falls_back_to_localhost_only_when_key_unset():
    settings = make_settings(api_key=None)
    assert is_authorized(None, "127.0.0.1", settings)
    assert is_authorized(None, "::1", settings)
    assert is_authorized(None, "testclient", settings)


def test_falls_back_rejects_non_localhost_when_key_unset():
    settings = make_settings(api_key=None)
    assert not is_authorized(None, "203.0.113.5", settings)
    assert not is_authorized(None, None, settings)


def test_bearer_prefix_is_required_exactly():
    settings = make_settings(api_key="secret123")
    assert not is_authorized("secret123", "1.2.3.4", settings)  # missing "Bearer " prefix
    assert not is_authorized("bearer secret123", "1.2.3.4", settings)  # wrong case
