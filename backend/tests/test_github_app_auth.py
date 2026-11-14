import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from app.github_app.auth import (
    JWT_TTL_SECONDS,
    AppIdentityProvider,
    InstallationTokenProvider,
    create_app_jwt,
    load_private_key,
)


@pytest.fixture(scope="module")
def keypair() -> tuple[str, str]:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("utf-8")
    public_pem = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode("utf-8")
    return private_pem, public_pem


class FakeClock:
    def __init__(self, t: float) -> None:
        self.t = t

    def now(self) -> float:
        return self.t


def test_create_app_jwt_has_correct_claims_and_verifies(keypair):
    private_pem, public_pem = keypair
    token = create_app_jwt("12345", private_pem, now=1_000_000)

    # verify_exp=False: the token's claimed "now" (1_000_000) is fake, not wall-clock
    # time, so of course it looks expired against the real clock -- the signature and
    # claim shape are what this test checks, not real-world expiry.
    decoded = jwt.decode(token, public_pem, algorithms=["RS256"], options={"verify_exp": False})
    assert decoded["iss"] == "12345"
    assert decoded["iat"] == 1_000_000 - 60
    assert decoded["exp"] == 1_000_000 + JWT_TTL_SECONDS


def test_create_app_jwt_ttl_is_under_githubs_ten_minute_cap(keypair):
    private_pem, _ = keypair
    token = create_app_jwt("1", private_pem, now=0)
    decoded = jwt.decode(token, options={"verify_signature": False})
    # GitHub requires exp - iat <= 10 minutes; iat is backdated 60s for clock-drift
    # tolerance, so the actual margin under the cap is JWT_TTL_SECONDS + 60 == 600s.
    assert decoded["exp"] - decoded["iat"] <= 10 * 60


def test_load_private_key_accepts_pem_text_directly(keypair):
    private_pem, _ = keypair
    assert load_private_key(private_pem) == private_pem.strip()


def test_load_private_key_accepts_a_file_path(tmp_path, keypair):
    private_pem, _ = keypair
    key_file = tmp_path / "key.pem"
    key_file.write_text(private_pem)
    assert load_private_key(str(key_file)) == private_pem


def test_installation_token_is_cached_until_near_expiry(keypair):
    private_pem, _ = keypair
    clock = FakeClock(1_000_000)
    calls = []

    def fetcher_with_expiry(installation_id, app_jwt, timeout):
        calls.append(installation_id)
        return {"token": f"token-{len(calls)}", "expires_at": "2033-01-01T00:00:00Z"}

    provider = InstallationTokenProvider("app-id", private_pem, clock=clock, token_fetcher=fetcher_with_expiry)

    first = provider.get_token(42)
    second = provider.get_token(42)

    assert first == second == "token-1"
    assert len(calls) == 1


def test_installation_token_refetches_after_expiry_safety_margin(keypair):
    private_pem, _ = keypair
    clock = FakeClock(1_000_000)
    calls = []

    def fetcher(installation_id, app_jwt, timeout):
        calls.append(installation_id)
        # expires 90 seconds after "now" on the fake clock, in GitHub's timestamp format
        import datetime

        expires = datetime.datetime.fromtimestamp(clock.now() + 90, tz=datetime.UTC)
        return {"token": f"token-{len(calls)}", "expires_at": expires.strftime("%Y-%m-%dT%H:%M:%SZ")}

    provider = InstallationTokenProvider("app-id", private_pem, clock=clock, token_fetcher=fetcher)

    first = provider.get_token(42)
    assert first == "token-1"
    assert len(calls) == 1

    # 50s later: still within the safety margin's reach of a 90s-lifetime token
    # (90 - 60 margin = 30s "safe" window) -- advance past it to force a refetch.
    clock.t += 50
    second = provider.get_token(42)
    assert second == "token-2"
    assert len(calls) == 2


def test_installation_tokens_are_cached_independently_per_installation(keypair):
    private_pem, _ = keypair
    clock = FakeClock(1_000_000)
    calls = []

    def fetcher(installation_id, app_jwt, timeout):
        calls.append(installation_id)
        return {"token": f"token-for-{installation_id}", "expires_at": "2033-01-01T00:00:00Z"}

    provider = InstallationTokenProvider("app-id", private_pem, clock=clock, token_fetcher=fetcher)

    assert provider.get_token(1) == "token-for-1"
    assert provider.get_token(2) == "token-for-2"
    assert provider.get_token(1) == "token-for-1"
    assert calls == [1, 2]


def test_app_identity_provider_resolves_bot_login_from_slug(keypair):
    private_pem, _ = keypair
    calls = []

    def fetcher(app_jwt, timeout):
        calls.append(app_jwt)
        return {"slug": "repomind", "id": 123}

    provider = AppIdentityProvider("app-id", private_pem, app_info_fetcher=fetcher)
    assert provider.get_bot_login() == "repomind[bot]"
    assert len(calls) == 1


def test_app_identity_provider_caches_bot_login_across_calls(keypair):
    private_pem, _ = keypair
    calls = []

    def fetcher(app_jwt, timeout):
        calls.append(app_jwt)
        return {"slug": "repomind", "id": 123}

    provider = AppIdentityProvider("app-id", private_pem, app_info_fetcher=fetcher)
    first = provider.get_bot_login()
    second = provider.get_bot_login()

    assert first == second == "repomind[bot]"
    assert len(calls) == 1  # fetched once, then cached for the life of the process
