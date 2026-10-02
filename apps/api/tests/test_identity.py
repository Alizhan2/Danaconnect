from datetime import date, timedelta

import pytest
from pydantic import ValidationError
from sqlalchemy import select

from app.auth import utcnow
from app.config import Settings, settings
from app.models import AuthChallenge, Consent, DocumentVersion, SessionToken


def test_origin_guard_precedes_auth_and_cookie_replay(integrated_api):
    api = integrated_api
    client = api.client()
    for headers in ({}, {"origin": "https://untrusted.example"}):
        response = client.post("/api/v1/auth/request-code", headers=headers, json={"email": "fresh@example.test"})
        assert response.status_code == 403
    issued = api.call("POST", "/auth/request-code", json={"email": "Fresh@EXAMPLE.test"})
    assert issued.status_code == 200
    credentials = {"challenge_id": issued.json()["challenge_id"], "code": issued.json()["debug_code"]}
    wrong = "000000" if credentials["code"] != "000000" else "111111"
    assert api.call("POST", "/auth/verify-code", json={**credentials, "code": wrong}).status_code == 400
    verified = api.call("POST", "/auth/verify-code", json=credentials)
    assert verified.status_code == 200
    assert verified.json()["email"] == "fresh@example.test"
    cookie = verified.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=lax" in cookie
    assert api.call("GET", "/auth/me").status_code == 200
    assert api.call("POST", "/auth/verify-code", json=credentials).status_code == 400
    assert api.call("POST", "/auth/logout").status_code == 200
    assert api.call("GET", "/auth/me").status_code == 401
    with api.factory() as db:
        challenge = db.get(AuthChallenge, credentials["challenge_id"])
        assert challenge.code_hash != credentials["code"] and challenge.consumed_at is not None
        assert list(db.scalars(select(SessionToken))) == []


def test_otp_attempt_limit_and_new_code_invalidates_previous(integrated_api):
    api = integrated_api
    issued = api.call("POST", "/auth/request-code", json={"email": "codes@example.test"}).json()
    wrong = "000000" if issued["debug_code"] != "000000" else "111111"
    for _ in range(settings.otp_max_attempts):
        assert api.call("POST", "/auth/verify-code", json={"challenge_id": issued["challenge_id"], "code": wrong}).status_code == 400
    assert api.call("POST", "/auth/verify-code", json={"challenge_id": issued["challenge_id"], "code": issued["debug_code"]}).status_code == 400
    assert api.call("POST", "/auth/request-code", json={"email": "codes@example.test"}).status_code == 429
    with api.factory() as db:
        db.get(AuthChallenge, issued["challenge_id"]).created_at = utcnow() - timedelta(minutes=2)
        db.commit()
    newer = api.call("POST", "/auth/request-code", json={"email": "codes@example.test"})
    assert newer.status_code == 200
    with api.factory() as db:
        assert db.get(AuthChallenge, issued["challenge_id"]).consumed_at is not None


def test_mentee_registration_requires_dob_consents_and_admin_review(integrated_api):
    api = integrated_api
    api.login("newcomer", "newcomer@example.test")
    response = api.call("PUT", "/me/profile", "newcomer", json=api.profile(birth_date=None))
    assert response.status_code == 200 and response.json()["profile_completed"] is False
    assert api.call("POST", "/me/submit-registration", "newcomer").status_code == 409
    future = (date.today() + timedelta(days=1)).isoformat()
    assert api.call("PUT", "/me/profile", "newcomer", json=api.profile(birth_date=future)).status_code == 422
    valid = api.call("PUT", "/me/profile", "newcomer", json=api.profile())
    assert valid.status_code == 200 and valid.json()["profile_completed"] is True
    assert api.call("POST", "/me/submit-registration", "newcomer").status_code == 409
    accepted = api.call("POST", f"/documents/{api.ids['version']}/consent", "newcomer")
    assert accepted.status_code == 200 and accepted.json()["method"] == "authenticated_checkbox"
    again = api.call("POST", f"/documents/{api.ids['version']}/consent", "newcomer")
    assert again.json()["id"] == accepted.json()["id"]
    assert api.call("POST", "/me/submit-registration", "newcomer").json()["account_status"] == "pending"
    assert api.call("GET", "/participations", "newcomer").status_code == 403
    assert api.call("GET", "/admin/registrations", "mentee").status_code == 403
    approved = api.call("POST", f"/admin/registrations/{api.ids['newcomer']}/review", "admin", json={"decision": "approved", "reason": "Sample reviewed"})
    assert approved.status_code == 200 and approved.json()["account_status"] == "active"
    assert approved.json()["intake_open"] is False
    assert api.call("GET", "/participations", "newcomer").status_code == 200
    notification = api.call("GET", "/notifications", "newcomer").json()[0]
    assert api.call("PATCH", f"/notifications/{notification['id']}/read", "stranger").status_code == 404
    assert api.call("PATCH", f"/notifications/{notification['id']}/read", "newcomer").status_code == 200
    assert api.call("PUT", "/me/profile", "newcomer", json=api.profile("mentor")).status_code == 403
    assert api.call("PUT", "/me/profile", "newcomer", json=api.profile(role="admin")).status_code == 422


def test_new_required_version_blocks_existing_session_until_reaccepted(integrated_api):
    api = integrated_api
    assert api.call("GET", "/participations", "mentee").status_code == 200
    with api.factory() as db:
        newer = DocumentVersion(document_id=api.ids["document"], version="2", content="Updated sample terms", content_hash="b" * 64, published_at=utcnow() + timedelta(seconds=1))
        db.add(newer)
        db.commit()
        new_id = newer.id
    assert api.call("GET", "/auth/me", "mentee").status_code == 200
    assert api.call("GET", "/participations", "mentee").status_code == 403
    assert api.call("POST", f"/documents/{api.ids['version']}/consent", "mentee").status_code == 409
    required = api.call("GET", "/documents", "mentee").json()
    assert required[0]["id"] == new_id and required[0]["accepted"] is False
    assert api.call("POST", f"/documents/{new_id}/consent", "mentee").status_code == 200
    assert api.call("GET", "/participations", "mentee").status_code == 200
    with api.factory() as db:
        assert len(list(db.scalars(select(Consent).where(Consent.user_id == api.ids["mentee"])))) == 2


def test_public_mentor_response_excludes_personal_and_evidence_fields(integrated_api):
    api = integrated_api
    for path in ("/mentors", f"/mentors/{api.ids['mentor']}"):
        response = api.call("GET", path)
        assert response.status_code == 200
        assert "PRIVATE-PHONE" not in response.text and "private-evidence" not in response.text
        items = response.json() if isinstance(response.json(), list) else [response.json()]
        for item in items:
            assert not {"email", "phone", "birth_date", "evidence_urls"} & item.keys()


@pytest.mark.parametrize("changes", [{"auth_debug_code": True}, {"demo_mode": True}, {"auth_secret": "weak"}, {"trusted_origins": ["http://localhost:3000"]}])
def test_production_settings_reject_unsafe_configuration(changes):
    valid = {"_env_file": None, "environment": "production", "auth_secret": "unique-production-secret-of-at-least-32-characters", "trusted_origins": ["https://platform.example"], "demo_mode": False, "auth_debug_code": False}
    with pytest.raises(ValidationError):
        Settings(**{**valid, **changes})


def test_email_provider_disabled_returns_explicit_unavailability(integrated_api, monkeypatch):
    monkeypatch.setattr(settings, "auth_debug_code", False)
    response = integrated_api.call("POST", "/auth/request-code", json={"email": "sample@example.test"})
    assert response.status_code == 503 and "debug_code" not in response.text


def test_production_route_never_exposes_debug_and_sets_secure_cookie(integrated_api, monkeypatch):
    api = integrated_api
    issued = api.call("POST", "/auth/request-code", json={"email": "sample@example.com"}).json()
    monkeypatch.setattr(settings, "environment", "production")
    unavailable = api.call("POST", "/auth/request-code", json={"email": "another@example.com"})
    assert unavailable.status_code == 503 and "debug_code" not in unavailable.text
    verified = api.call("POST", "/auth/verify-code", json={"challenge_id": issued["challenge_id"], "code": issued["debug_code"]})
    assert verified.status_code == 200
    assert "secure" in verified.headers["set-cookie"].lower()


def test_expired_challenge_and_error_responses_do_not_echo_inputs(integrated_api):
    api = integrated_api
    issued = api.call("POST", "/auth/request-code", json={"email": "expired@example.test"}).json()
    with api.factory() as db:
        db.get(AuthChallenge, issued["challenge_id"]).expires_at = utcnow() - timedelta(seconds=1)
        db.commit()
    expired = api.call("POST", "/auth/verify-code", json={"challenge_id": issued["challenge_id"], "code": issued["debug_code"]})
    assert expired.status_code == 400 and issued["debug_code"] not in expired.text
    invalid = api.call("POST", "/auth/verify-code", json={"challenge_id": "example", "code": "PRIVATE-INVALID-CODE"})
    assert invalid.status_code == 422 and "PRIVATE-INVALID-CODE" not in invalid.text
