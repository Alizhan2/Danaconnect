"""Operator-authorized first-login MFA uses mailbox proof and a new pending seed."""
import base64
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from urllib.parse import parse_qs, urlsplit

from fastapi import HTTPException, Response
from fastapi.testclient import TestClient
import pytest
from sqlalchemy import func, select

from app.auth import generate_totp_secret, secret_hash, totp_code, utcnow
from app.delivery import decrypt_text, encrypt_text
from app.main import app
from app.models import AuditEvent, AuthChallenge, SessionToken, User
from app.models_delivery import AdminCredential, MFAChallenge, SessionAssurance
from app.routers import identity


def prepare(api, **changes):
    values = {"user_id": api.ids["admin"], "active": False, "last_used_step": -1,
              "enrollment_expires_at": utcnow() + timedelta(minutes=20), "encrypted_totp_secret": ""}
    values.update(changes)
    with api.factory() as db:
        row = AdminCredential(**values)
        db.add(row)
        db.commit()
        return row.id


def email_proof(api):
    # Simulate elapsed resend cooldown; OTP issuance and verification stay real.
    with api.factory() as db:
        for row in db.scalars(select(AuthChallenge).where(AuthChallenge.email == "admin@example.test")):
            row.created_at = utcnow() - timedelta(minutes=2)
        db.commit()
    requested = api.call("POST", "/auth/request-code", json={"email": "admin@example.test"})
    assert requested.status_code == 200, requested.text
    data = requested.json()
    return {"challenge_id": data["challenge_id"], "code": data["debug_code"]}


def enroll(api):
    response = api.call("POST", "/auth/verify-code", json=email_proof(api))
    assert response.status_code == 200, response.text
    assert "enrollment" in response.json()
    return response


def verify(api, data, code=None):
    return api.call("POST", "/auth/mfa/verify", json={
        "mfa_challenge_id": data["mfa_challenge_id"],
        "code": code or totp_code(data["enrollment"]["manual_entry_key"]),
    })


def test_pending_admin_enrollment_requires_email_and_activates_only_after_totp(integrated_api):
    api = integrated_api
    identifier = prepare(api)
    proof = email_proof(api)
    wrong = {**proof, "code": "000000" if proof["code"] != "000000" else "111111"}
    denied = api.call("POST", "/auth/verify-code", json=wrong)
    assert denied.status_code == 400 and "enrollment" not in denied.text
    with api.factory() as db:
        assert db.get(AdminCredential, identifier).encrypted_totp_secret == ""
        assert db.scalar(select(MFAChallenge)) is None
    response = api.call("POST", "/auth/verify-code", json=proof)
    data = response.json()
    assert response.status_code == 200 and data["mfa_required"] is True
    assert "set-cookie" not in response.headers and response.headers["cache-control"] == "no-store"
    assert set(data["enrollment"]) == {"qr_data_url", "manual_entry_key"}
    secret = data["enrollment"]["manual_entry_key"]
    svg = base64.b64decode(data["enrollment"]["qr_data_url"].split(",", 1)[1])
    assert b"<svg" in svg and b"<path" in svg and secret.encode() not in svg
    assert api.call("GET", "/admin/me").status_code == 401
    with api.factory() as db:
        credential = db.get(AdminCredential, identifier)
        assert not credential.active and credential.last_used_step == -1
        assert decrypt_text(credential.encrypted_totp_secret) == secret
        assert db.scalar(select(SessionToken)) is None
        assert db.scalar(select(AuthChallenge).where(AuthChallenge.id == proof["challenge_id"])).consumed_at
    assert api.call("POST", "/auth/verify-code", json=proof).status_code == 400
    accepted = verify(api, data)
    assert accepted.status_code == 200 and accepted.json()["role"] == "admin"
    assert "httponly" in accepted.headers["set-cookie"].lower()
    assert accepted.headers["cache-control"] == "no-store"
    assert "manual_entry_key" not in accepted.text and "qr_data_url" not in accepted.text
    assert api.call("GET", "/admin/me").status_code == 200
    assert verify(api, data).status_code == 410
    with api.factory() as db:
        credential = db.get(AdminCredential, identifier)
        assert credential.active and credential.enrollment_expires_at is None and credential.last_used_step >= 0
        assert db.scalar(select(func.count(SessionAssurance.id))) == 1
        audit = db.scalars(select(AuditEvent).where(AuditEvent.action.like("admin.mfa_enroll%"))).all()
        assert {row.action for row in audit} == {"admin.mfa_enrollment_started", "admin.mfa_enrolled"}
        assert all(secret not in str(row.detail) for row in audit)


def test_fresh_email_proof_rotates_pending_seed_and_revokes_old_challenges(integrated_api):
    api = integrated_api
    identifier = prepare(api)
    first = enroll(api).json()
    old_secret = first["enrollment"]["manual_entry_key"]
    second = enroll(api).json()
    assert second["enrollment"]["manual_entry_key"] != old_secret
    assert old_secret not in str(second)
    assert verify(api, first).status_code == 410
    with api.factory() as db:
        assert decrypt_text(db.get(AdminCredential, identifier).encrypted_totp_secret) == second["enrollment"]["manual_entry_key"]
        assert db.scalar(select(func.count(MFAChallenge.id)).where(MFAChallenge.consumed_at.is_(None))) == 1
    assert verify(api, second).status_code == 200


def test_active_credential_never_returns_old_seed_even_with_an_enrollment_date(integrated_api):
    api = integrated_api
    old = generate_totp_secret()
    identifier = prepare(api, active=True, encrypted_totp_secret=encrypt_text(old))
    data = api.call("POST", "/auth/verify-code", json=email_proof(api)).json()
    assert data["mfa_required"] is True and "enrollment" not in data and old not in str(data)
    with api.factory() as db:
        assert decrypt_text(db.get(AdminCredential, identifier).encrypted_totp_secret) == old


@pytest.mark.parametrize("changes", [
    {"enrollment_expires_at": None}, {"enrollment_expires_at": utcnow() - timedelta(seconds=1)},
    {"last_used_step": 0},
])
def test_disabled_or_expired_credentials_never_use_local_debug_session_bypass(integrated_api, changes):
    api = integrated_api
    old = generate_totp_secret()
    prepare(api, encrypted_totp_secret=encrypt_text(old), **changes)
    response = api.call("POST", "/auth/verify-code", json=email_proof(api))
    assert response.status_code == 503 and old not in response.text and "enrollment" not in response.text
    assert "set-cookie" not in response.headers
    with api.factory() as db:
        assert db.scalar(select(SessionToken)) is None


@pytest.mark.parametrize("status", ["suspended", "draft", "pending", "changes_requested"])
def test_non_active_admin_cannot_enroll(integrated_api, status):
    api = integrated_api
    identifier = prepare(api)
    with api.factory() as db:
        db.get(User, api.ids["admin"]).account_status = status
        db.commit()
    response = api.call("POST", "/auth/verify-code", json=email_proof(api))
    assert response.status_code == 403 and "enrollment" not in response.text
    with api.factory() as db:
        assert db.get(AdminCredential, identifier).encrypted_totp_secret == ""
        assert db.scalar(select(SessionToken)) is None


def test_non_admin_never_receives_operator_enrollment(integrated_api):
    api = integrated_api
    with api.factory() as db:
        db.add(AdminCredential(user_id=api.ids["mentee"], active=False, last_used_step=-1,
                               encrypted_totp_secret="", enrollment_expires_at=utcnow() + timedelta(minutes=10)))
        db.commit()
    response = api.login("mentee", "mentee@example.test")
    assert response.json()["role"] == "mentee" and "enrollment" not in response.json()


@pytest.mark.parametrize("expiry", ["challenge", "operator"])
def test_totp_must_be_confirmed_before_both_deadlines(integrated_api, expiry):
    api = integrated_api
    identifier = prepare(api, enrollment_expires_at=utcnow() + timedelta(seconds=30))
    data = enroll(api).json()
    assert 0 < data["expires_in"] <= 30
    with api.factory() as db:
        if expiry == "challenge":
            db.scalar(select(MFAChallenge)).expires_at = utcnow() - timedelta(seconds=1)
        else:
            db.get(AdminCredential, identifier).enrollment_expires_at = utcnow() - timedelta(seconds=1)
        db.commit()
    assert verify(api, data).status_code == 410
    with api.factory() as db:
        assert not db.get(AdminCredential, identifier).active and db.scalar(select(SessionToken)) is None


@pytest.mark.parametrize("expiry", ["challenge", "operator"])
def test_expiry_during_totp_validation_cannot_activate_credential(integrated_api, monkeypatch, expiry):
    api = integrated_api
    identifier = prepare(api)
    data = enroll(api).json()
    future = utcnow() + timedelta(hours=1)
    with api.factory() as db:
        credential = db.get(AdminCredential, identifier)
        challenge = db.scalar(select(MFAChallenge))
        if expiry == "challenge":
            credential.enrollment_expires_at = future + timedelta(hours=1)
        else:
            challenge.expires_at = future + timedelta(hours=1)
        db.commit()
    original_match = identity.matching_totp_step
    def finish_after_expiry(*args):
        monkeypatch.setattr(identity, "utcnow", lambda: future)
        return original_match(*args)
    monkeypatch.setattr(identity, "matching_totp_step", finish_after_expiry)
    assert verify(api, data).status_code == 410
    with api.factory() as db:
        assert not db.get(AdminCredential, identifier).active
        assert db.scalar(select(SessionToken)) is None


def test_wrong_totp_keeps_pending_seed_until_attempt_limit_then_allows_new_email_proof(integrated_api, monkeypatch):
    api = integrated_api
    identifier = prepare(api)
    data = enroll(api).json()
    with api.factory() as db:
        encrypted = db.get(AdminCredential, identifier).encrypted_totp_secret
    with monkeypatch.context() as patch:
        patch.setattr(identity, "matching_totp_step", lambda *_: None)
        for attempt in range(5):
            assert verify(api, data, "000000").status_code == 400
            with api.factory() as db:
                row = db.get(AdminCredential, identifier)
                assert not row.active
                assert row.encrypted_totp_secret == (encrypted if attempt < 4 else "")
    assert verify(api, data).status_code == 410
    new = enroll(api).json()
    assert new["enrollment"]["manual_entry_key"] != data["enrollment"]["manual_entry_key"]
    assert verify(api, new).status_code == 200


def test_qr_failure_rolls_back_email_proof_and_pending_secret_for_safe_retry(integrated_api, monkeypatch):
    api = integrated_api
    identifier = prepare(api)
    proof = email_proof(api)
    with monkeypatch.context() as patch:
        def unavailable(_):
            raise RuntimeError("Synthetic renderer unavailable")
        patch.setattr(identity, "qr_data_url", unavailable)
        response = api.call("POST", "/auth/verify-code", json=proof)
        assert response.status_code == 503 and "Synthetic renderer" not in response.text
    with api.factory() as db:
        assert db.get(AdminCredential, identifier).encrypted_totp_secret == ""
        assert db.get(AuthChallenge, proof["challenge_id"]).consumed_at is None
    assert api.call("POST", "/auth/verify-code", json=proof).status_code == 200


def test_parallel_confirmation_creates_one_assured_session(integrated_api):
    api = integrated_api
    prepare(api)
    data = enroll(api).json()
    payload = {"mfa_challenge_id": data["mfa_challenge_id"], "code": totp_code(data["enrollment"]["manual_entry_key"])}
    def confirm(_):
        with TestClient(app) as client:
            return client.post("/api/v1/auth/mfa/verify", headers={"origin": api.origin}, json=payload).status_code
    with ThreadPoolExecutor(max_workers=4) as pool:
        statuses = list(pool.map(confirm, range(4)))
    assert statuses.count(200) == 1 and statuses.count(410) == 3
    with api.factory() as db:
        assert db.scalar(select(func.count(SessionToken.id))) == 1
        assert db.scalar(select(func.count(SessionAssurance.id))) == 1


def test_parallel_email_confirmation_generates_one_pending_challenge(integrated_api):
    api = integrated_api
    prepare(api)
    proof = email_proof(api)
    def confirm(_):
        with TestClient(app) as client:
            response = client.post("/api/v1/auth/verify-code", headers={"origin": api.origin}, json=proof)
            return response.status_code
    with ThreadPoolExecutor(max_workers=4) as pool:
        statuses = list(pool.map(confirm, range(4)))
    assert statuses.count(200) == 1 and statuses.count(400) == 3
    with api.factory() as db:
        assert db.scalar(select(func.count(MFAChallenge.id)).where(MFAChallenge.consumed_at.is_(None))) == 1
        assert db.scalar(select(SessionToken)) is None


def test_pending_state_blocks_existing_assurance_and_direct_session_issuance(integrated_api):
    api = integrated_api
    api.login("admin", "admin@example.test")  # Explicit local synthetic flow before provisioning.
    with api.factory() as db:
        session = db.scalar(select(SessionToken).where(SessionToken.user_id == api.ids["admin"]))
        db.add(SessionAssurance(session_id=session.id))
        db.commit()
    prepare(api)
    assert api.call("GET", "/admin/me", "admin").status_code == 403
    with api.factory() as db:
        user = db.get(User, api.ids["admin"])
        for verified in (False, True):
            with pytest.raises(HTTPException) as denied:
                identity.issue_session(db, user, Response(), mfa_verified=verified)
            assert denied.value.status_code == 403


def test_google_does_not_bypass_pending_admin_enrollment(integrated_api, monkeypatch):
    api = integrated_api
    identifier = prepare(api)
    from app.config import settings
    monkeypatch.setattr(settings, "google_client_id", "synthetic-client")
    monkeypatch.setattr(settings, "google_client_secret", "synthetic-secret")
    monkeypatch.setattr(settings, "google_redirect_uri", "http://localhost/callback")
    start = api.call("GET", "/auth/google/start").json()
    state = parse_qs(urlsplit(start["authorization_url"]).query)["state"][0]
    monkeypatch.setattr(identity.httpx, "post", lambda *_a, **_k: type("Token", (), {
        "status_code": 200, "json": lambda self: {"id_token": "synthetic-id-token"}})())
    monkeypatch.setattr(identity, "verify_google_id_token", lambda *_: {"email": "admin@example.test", "sub": "synthetic-subject"})
    response = api.client().get("/api/v1/auth/google/callback", params={"state": state, "code": "synthetic"}, follow_redirects=False)
    assert response.status_code == 403 and "set-cookie" not in response.headers
    with api.factory() as db:
        assert db.get(AdminCredential, identifier).encrypted_totp_secret == ""
        assert db.scalar(select(SessionToken)) is None
