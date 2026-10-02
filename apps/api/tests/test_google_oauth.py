"""Google route checks with synthetic providers; no live Google requests."""
from urllib.parse import parse_qs, urlsplit
import time

import pytest
from sqlalchemy import select

from app.config import settings
from app.models import SessionToken
from app.models_delivery import OAuthState
from app.routers import identity


@pytest.fixture(scope="module")
def signing_key():
    from cryptography.hazmat.primitives.asymmetric import rsa
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture
def configured_google(monkeypatch):
    monkeypatch.setattr(settings, "google_client_id", "isolated-client-id")
    monkeypatch.setattr(settings, "google_client_secret", "isolated-client-secret")
    monkeypatch.setattr(settings, "google_redirect_uri", "http://localhost:8000/api/v1/auth/google/callback")


def start_google(api):
    response = api.call("GET", "/auth/google/start?locale=kk")
    assert response.status_code == 200
    params = parse_qs(urlsplit(response.json()["authorization_url"]).query)
    assert params["code_challenge_method"] == ["S256"]
    assert params["scope"] == ["openid email profile"]
    return params["state"][0]


def test_google_unconfigured_fails_explicitly(integrated_api):
    assert integrated_api.call("GET", "/auth/google/start").status_code == 503


def test_google_callback_requires_matching_browser_and_unconsumed_state(integrated_api, configured_google, monkeypatch):
    api = integrated_api
    state = start_google(api)
    api.client().cookies.clear()
    def forbidden_network(*args, **kwargs):
        pytest.fail("Google exchange must not happen before browser/state checks")
    monkeypatch.setattr(identity.httpx, "post", forbidden_network)
    response = api.call("GET", "/auth/google/callback", params={"state": state, "code": "synthetic-code"})
    assert response.status_code == 400
    with api.factory() as db:
        assert db.scalar(select(OAuthState)).consumed_at is None
        assert db.scalar(select(SessionToken)) is None


@pytest.mark.parametrize("role, expected_status", [("mentee", 303), ("admin", 403)])
def test_google_allows_participant_but_never_admin_session(integrated_api, configured_google, monkeypatch, role, expected_status):
    api = integrated_api
    state = start_google(api)
    monkeypatch.setattr(identity.httpx, "post", lambda *a, **k: type("SyntheticToken", (), {
        "status_code": 200, "json": lambda self: {"id_token": "synthetic-id-token"}})())
    monkeypatch.setattr(identity, "verify_google_id_token", lambda *a: {
        "email": f"{role}@example.test", "sub": "synthetic-google-subject"})
    response = api.client().get("/api/v1/auth/google/callback",
        params={"state": state, "code": "synthetic-code"}, follow_redirects=False)
    assert response.status_code == expected_status
    with api.factory() as db:
        state_row = db.scalar(select(OAuthState))
        assert state_row.consumed_at is not None
        assert state_row.encrypted_verifier == ""
        assert (db.scalar(select(SessionToken)) is not None) is (role == "mentee")
    assert api.call("GET", "/auth/google/callback", params={"state": state, "code": "synthetic-code"}).status_code == 400


@pytest.mark.parametrize("changes", [
    {"email_verified": False}, {"nonce": "wrong"}, {"azp": "other-client"},
    {"email": "user@example.test"}, {"sub": ""},
    {"aud": ["isolated-client-id", "other-client"]},
])
def test_google_claim_validation_rejects_untrusted_identity(configured_google, monkeypatch, signing_key, changes):
    from fastapi import HTTPException
    from app.auth import secret_hash
    claims = {"email": "synthetic@gmail.com", "email_verified": True,
              "nonce": "synthetic-nonce", "sub": "synthetic-subject", "aud": "isolated-client-id",
              "iss": "https://accounts.google.com", "iat": int(time.time()), "exp": int(time.time()) + 60}
    claims.update(changes)
    class FakeKeyClient:
        def __init__(self, *args, **kwargs):
            pass
        def get_signing_key_from_jwt(self, token):
            return type("Key", (), {"key": signing_key.public_key()})()
    monkeypatch.setattr(identity.jwt, "PyJWKClient", FakeKeyClient)
    token = identity.jwt.encode(claims, signing_key, algorithm="RS256")
    with pytest.raises(HTTPException) as error:
        identity.verify_google_id_token(token, secret_hash("synthetic-nonce"))
    assert error.value.status_code == 400


@pytest.mark.parametrize("changes, valid", [
    ({}, True), ({"email": "synthetic@example.test", "hd": "example.test"}, True),
    ({"aud": "wrong-client"}, False), ({"iss": "https://untrusted.example"}, False),
    ({"exp": 1}, False),
])
def test_google_signed_jwt_validates_audience_issuer_expiry(configured_google, monkeypatch, signing_key, changes, valid):
    from fastapi import HTTPException
    from app.auth import secret_hash
    claims = {"email": "synthetic@gmail.com", "email_verified": True,
              "nonce": "synthetic-nonce", "sub": "synthetic-subject", "aud": "isolated-client-id",
              "iss": "https://accounts.google.com", "iat": int(time.time()), "exp": int(time.time()) + 60}
    claims.update(changes)
    class FakeKeyClient:
        def __init__(self, *args, **kwargs):
            pass
        def get_signing_key_from_jwt(self, token):
            return type("Key", (), {"key": signing_key.public_key()})()
    monkeypatch.setattr(identity.jwt, "PyJWKClient", FakeKeyClient)
    token = identity.jwt.encode(claims, signing_key, algorithm="RS256")
    if valid:
        assert identity.verify_google_id_token(token, secret_hash("synthetic-nonce")) == claims
    else:
        with pytest.raises(HTTPException) as error:
            identity.verify_google_id_token(token, secret_hash("synthetic-nonce"))
        assert error.value.status_code == 400
