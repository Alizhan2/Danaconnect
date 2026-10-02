"""MFA regressions use only synthetic credentials in isolated fixture storage."""
from datetime import timedelta

from sqlalchemy import select

from app.auth import generate_totp_secret, secret_hash, totp_code, utcnow
from app.config import settings
from app.delivery import encrypt_text
from app.models import SessionToken
from app.models_delivery import AdminCredential, MFAChallenge, SessionAssurance


def start_admin_challenge(api):
    issued = api.call("POST", "/auth/request-code", json={"email": "admin@example.test"})
    assert issued.status_code == 200
    verified = api.call("POST", "/auth/verify-code", json={
        "challenge_id": issued.json()["challenge_id"], "code": issued.json()["debug_code"]})
    assert verified.status_code == 200
    assert verified.json()["mfa_required"] is True
    assert verified.json()["expires_in"] == settings.admin_mfa_minutes * 60
    assert "set-cookie" not in verified.headers
    return verified.json()["mfa_challenge_id"]


def provision(api):
    secret = generate_totp_secret()
    with api.factory() as db:
        db.add(AdminCredential(user_id=api.ids["admin"], encrypted_totp_secret=encrypt_text(secret)))
        db.commit()
    return secret


def test_email_then_totp_creates_assured_admin_session_and_rejects_replay(integrated_api):
    api = integrated_api
    secret = provision(api)
    token = start_admin_challenge(api)
    assert api.call("GET", "/auth/me").status_code == 401
    payload = {"mfa_challenge_id": token, "code": totp_code(secret)}
    verified = api.call("POST", "/auth/mfa/verify", json=payload)
    assert verified.status_code == 200
    assert verified.json()["role"] == "admin"
    assert "httponly" in verified.headers["set-cookie"].lower()
    assert api.call("GET", "/admin/registrations").status_code == 200
    with api.factory() as db:
        session = db.scalar(select(SessionToken).where(SessionToken.user_id == api.ids["admin"]))
        assert db.scalar(select(SessionAssurance).where(SessionAssurance.session_id == session.id)) is not None
        credential = db.scalar(select(AdminCredential).where(AdminCredential.user_id == api.ids["admin"]))
        assert credential.last_used_step >= 0
    assert api.call("POST", "/auth/mfa/verify", json=payload).status_code == 410


def test_expired_mfa_explains_request_new_email_code_without_reenrollment(integrated_api):
    api = integrated_api
    secret = provision(api)
    token = start_admin_challenge(api)
    with api.factory() as db:
        db.scalar(select(MFAChallenge).where(MFAChallenge.token_hash == secret_hash(token))).expires_at = utcnow() - timedelta(seconds=1)
        db.commit()
    expired = api.call("POST", "/auth/mfa/verify", json={"mfa_challenge_id": token, "code": totp_code(secret)})
    assert expired.status_code == 410
    assert "новый код по email" in expired.json()["detail"]
    assert "Повторно сканировать QR не нужно" in expired.json()["detail"]
    assert api.call("GET", "/auth/me").status_code == 401


def test_wrong_mfa_attempts_lock_challenge_without_session(integrated_api):
    api = integrated_api
    provision(api)
    token = start_admin_challenge(api)
    # Stub only code matching so this test cannot accidentally choose a valid code.
    from unittest.mock import patch
    with patch("app.routers.identity.matching_totp_step", return_value=None):
        for _ in range(settings.otp_max_attempts):
            rejected = api.call("POST", "/auth/mfa/verify", json={"mfa_challenge_id": token, "code": "000000"})
            assert rejected.status_code == 400
    locked = api.call("POST", "/auth/mfa/verify", json={"mfa_challenge_id": token, "code": "000000"})
    assert locked.status_code == 410
    with api.factory() as db:
        assert db.scalar(select(SessionToken)) is None


def test_admin_without_mfa_cannot_bypass_when_debug_disabled(integrated_api, monkeypatch):
    api = integrated_api
    issued = api.call("POST", "/auth/request-code", json={"email": "admin@example.test"}).json()
    monkeypatch.setattr(settings, "auth_debug_code", False)
    denied = api.call("POST", "/auth/verify-code", json={"challenge_id": issued["challenge_id"], "code": issued["debug_code"]})
    assert denied.status_code == 503
    assert "настроить MFA" in denied.json()["detail"]
    assert "set-cookie" not in denied.headers
    with api.factory() as db:
        assert db.scalar(select(SessionToken)) is None
