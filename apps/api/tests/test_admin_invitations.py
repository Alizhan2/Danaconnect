"""Synthetic administrator admission; no production accounts or providers."""
import base64
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
import json
from pathlib import Path
import re

from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
import pytest
from sqlalchemy import create_engine, func, inspect, select

from app.auth import generate_totp_secret, secret_hash, totp_code, utcnow
from app.config import settings
from app.delivery import decrypt_text, encrypt_text
from app.main import app
from app.models import AuditEvent, AuthChallenge, SessionToken, User
from app.models_admin_invitations import AdminInvitation, AdminInvitationChallenge
from app.models_delivery import AdminCredential, EmailOutbox, SessionAssurance


@pytest.fixture
def invitation_api(integrated_api, monkeypatch):
    api = integrated_api
    monkeypatch.setattr(settings, "email_provider", "console")
    secret = generate_totp_secret()
    token = __import__("secrets").token_urlsafe(48)
    with api.factory() as db:
        db.add(AdminCredential(user_id=api.ids["admin"], encrypted_totp_secret=encrypt_text(secret)))
        session = SessionToken(user_id=api.ids["admin"], token_hash=secret_hash(token), expires_at=utcnow() + timedelta(days=1))
        db.add(session)
        db.flush()
        db.add(SessionAssurance(session_id=session.id))
        db.commit()
    # The inviter's real email/TOTP flow is covered by test_admin_mfa. Here
    # persist synthetic session assurance while retaining all authorization
    # dependencies; never override require_admin or current-user checks.
    api.client().cookies.set("dc_session", token)
    api.clients["recipient"] = api.stack.enter_context(TestClient(app))
    return api


def create(api, email="new-admin@example.test", locale="ru"):
    response = api.call("POST", "/admin/invitations", json={"email": email, "full_name": "New Administrator", "locale": locale})
    assert response.status_code == 201, response.text
    data = response.json()
    with api.factory() as db:
        row = db.scalar(select(EmailOutbox).where(EmailOutbox.dedup_key == "admin-invitation:" + data["id"]))
        mail = json.loads(decrypt_text(row.encrypted_payload))
        token = re.search(r"#token=([A-Za-z0-9_-]+)", mail["text"])[1]
    return data, token


def request_otp(api, token):
    response = api.call("POST", "/auth/admin-invitations/request-code", who="recipient", json={"token": token})
    assert response.status_code == 200, response.text
    return response.json()


def enroll(api, token):
    otp = request_otp(api, token)
    response = api.call("POST", "/auth/admin-invitations/verify-code", who="recipient", json={
        "token": token, "challenge_id": otp["challenge_id"], "code": otp["debug_code"]})
    assert response.status_code == 200, response.text
    assert "set-cookie" not in response.headers
    assert response.headers["cache-control"] == "no-store"
    return response.json(), otp


def accept(api, enrollment):
    return api.call("POST", "/auth/admin-invitations/accept", who="recipient", json={
        "enrollment_token": enrollment["enrollment_token"], "code": totp_code(enrollment["manual_entry_key"])})


def test_complete_admission_mail_otp_local_qr_totp_creates_single_assured_session(invitation_api):
    api = invitation_api
    data, token = create(api)
    assert data["status"] == "pending" and data["delivery_status"] == "pending"
    assert data["invited_by"] == api.ids["admin"]
    assert token not in json.dumps(data)
    with api.factory() as db:
        assert db.scalar(select(User).where(User.email == data["email"])) is None
        assert db.get(AdminInvitation, data["id"]).token_hash == secret_hash(token)
    enrollment, otp = enroll(api, token)
    assert enrollment["email"] == data["email"] and enrollment["full_name"] == data["full_name"]
    assert enrollment["expires_in"] == 300
    assert enrollment["totp_uri"].startswith("otpauth://totp/DanaConnect%3A")
    svg = base64.b64decode(enrollment["qr_data_url"].split(",", 1)[1])
    assert b"<svg" in svg and b"<path" in svg
    assert b"http://www.w3.org/2000/svg" in svg  # Namespace, no network request.
    assert enrollment["manual_entry_key"].encode() not in svg
    assert api.call("GET", "/auth/me", who="recipient").status_code == 401
    with api.factory() as db:
        row = db.get(AdminInvitation, data["id"])
        assert row.proof_hash == secret_hash(enrollment["enrollment_token"])
        assert enrollment["manual_entry_key"] not in row.encrypted_seed
        assert db.scalar(select(User).where(User.email == data["email"])) is None
    accepted = accept(api, enrollment)
    assert accepted.status_code == 200 and accepted.json()["role"] == "admin"
    assert "httponly" in accepted.headers["set-cookie"].lower()
    assert api.call("GET", "/admin/invitations", who="recipient").status_code == 200
    with api.factory() as db:
        row = db.get(AdminInvitation, data["id"])
        assert row.status == "accepted" and row.accepted_at and row.encrypted_seed == "" and row.proof_hash is None
        credential = db.scalar(select(AdminCredential).where(AdminCredential.user_id == accepted.json()["id"]))
        assert decrypt_text(credential.encrypted_totp_secret) == enrollment["manual_entry_key"] and credential.last_used_step >= 0
        session = db.scalar(select(SessionToken).where(SessionToken.user_id == accepted.json()["id"]))
        assert db.scalar(select(SessionAssurance).where(SessionAssurance.session_id == session.id)) is not None
        assert db.scalar(select(EmailOutbox).where(EmailOutbox.dedup_key == "admin-invitation:" + data["id"])).encrypted_payload == ""
        audit = json.dumps([row.detail for row in db.scalars(select(AuditEvent)).all()])
        assert token not in audit and enrollment["enrollment_token"] not in audit and enrollment["manual_entry_key"] not in audit
    assert accept(api, enrollment).status_code == 410
    assert api.call("DELETE", "/admin/invitations/" + data["id"]).status_code == 409


def test_demo_admin_cannot_invite_list_or_revoke(integrated_api):
    api = integrated_api
    for method, path, kwargs in [
        ("GET", "/admin/invitations", {}),
        ("POST", "/admin/invitations", {"json": {"email": "new-admin@example.test", "full_name": "New Admin", "locale": "ru"}}),
        ("DELETE", "/admin/invitations/unknown", {}),
    ]:
        response = api.call(method, path, who="admin", **kwargs)
        assert response.status_code == 403
    with api.factory() as db:
        assert db.scalar(select(AdminInvitation)) is None


@pytest.mark.parametrize("who", ["recipient", "mentor", "mentee"])
def test_non_admin_cannot_invite(invitation_api, who):
    api = invitation_api
    response = api.call("POST", "/admin/invitations", who=who, json={"email": "new-admin@example.test", "full_name": "New Admin"})
    assert response.status_code in {401, 403}


@pytest.mark.parametrize("email", ["admin@example.test", "mentor@example.test", "mentee@example.test", "stranger@example.test"])
def test_existing_accounts_never_promoted_or_rotated(invitation_api, email):
    api = invitation_api
    response = api.call("POST", "/admin/invitations", json={"email": email.upper(), "full_name": "New Admin"})
    assert response.status_code == 409
    with api.factory() as db:
        assert db.scalar(select(AdminInvitation)) is None


@pytest.mark.parametrize("locale,subject", [("ru", "приглашение"), ("kk", "шақыруы"), ("en", "invitation")])
def test_localized_invite_encrypted_and_never_in_admin_response(invitation_api, locale, subject):
    api = invitation_api
    data, token = create(api, locale=locale)
    response = api.call("GET", "/admin/invitations")
    assert response.status_code == 200 and response.json()["items"][0]["locale"] == locale
    assert token not in response.text and "token_hash" not in response.text and "encrypted_seed" not in response.text
    with api.factory() as db:
        outbox = db.scalar(select(EmailOutbox))
        assert token not in outbox.encrypted_payload
        mail = json.loads(decrypt_text(outbox.encrypted_payload))
        assert subject in mail["subject"]
        assert "/admin/accept-invite#token=" in mail["text"]
        assert mail["recipient"] == data["email"]


def test_duplicate_pending_invite_normalized_email_and_expired_replacement(invitation_api):
    api = invitation_api
    data, token = create(api)
    duplicate = api.call("POST", "/admin/invitations", json={"email": " NEW-ADMIN@EXAMPLE.TEST ", "full_name": "Another Name"})
    assert duplicate.status_code == 409
    with api.factory() as db:
        db.get(AdminInvitation, data["id"]).expires_at = utcnow() - timedelta(seconds=1)
        db.commit()
    replacement, replacement_token = create(api)
    assert replacement["id"] != data["id"] and replacement_token != token
    with api.factory() as db:
        assert db.get(AdminInvitation, data["id"]).status == "expired"
        old_mail = db.scalar(select(EmailOutbox).where(EmailOutbox.dedup_key == "admin-invitation:" + data["id"]))
        assert old_mail.status == "failed" and old_mail.encrypted_payload == ""
    assert api.call("POST", "/auth/admin-invitations/request-code", who="recipient", json={"token": token}).status_code == 410


def test_invitation_otp_cannot_be_used_as_ordinary_login(invitation_api):
    api = invitation_api
    data, token = create(api)
    otp = request_otp(api, token)
    ordinary = api.call("POST", "/auth/verify-code", who="recipient", json={"challenge_id": otp["challenge_id"], "code": otp["debug_code"]})
    assert ordinary.status_code == 400 and "set-cookie" not in ordinary.headers
    enrollment_response = api.call("POST", "/auth/admin-invitations/verify-code", who="recipient", json={
        "token": token, "challenge_id": otp["challenge_id"], "code": otp["debug_code"]})
    assert enrollment_response.status_code == 200
    with api.factory() as db:
        assert db.scalar(select(User).where(User.email == data["email"])) is None


def test_otp_bound_to_exact_invitation_and_email(invitation_api):
    api = invitation_api
    _, token_a = create(api)
    _, token_b = create(api, email="other-admin@example.test")
    otp_a = request_otp(api, token_a)
    rejected = api.call("POST", "/auth/admin-invitations/verify-code", who="recipient", json={
        "token": token_b, "challenge_id": otp_a["challenge_id"], "code": otp_a["debug_code"]})
    assert rejected.status_code == 400
    verified = api.call("POST", "/auth/admin-invitations/verify-code", who="recipient", json={
        "token": token_a, "challenge_id": otp_a["challenge_id"], "code": otp_a["debug_code"]})
    assert verified.status_code == 200
    replay = api.call("POST", "/auth/admin-invitations/verify-code", who="recipient", json={
        "token": token_a, "challenge_id": otp_a["challenge_id"], "code": otp_a["debug_code"]})
    assert replay.status_code == 400


def test_resend_does_not_allow_old_code_and_does_not_consume_new_otp(invitation_api):
    api = invitation_api
    _, token = create(api)
    first = request_otp(api, token)
    assert api.call("POST", "/auth/admin-invitations/request-code", who="recipient", json={"token": token}).status_code == 429
    with api.factory() as db:
        db.get(AdminInvitationChallenge, first["challenge_id"]).created_at = utcnow() - timedelta(seconds=61)
        db.commit()
    second = request_otp(api, token)
    old = api.call("POST", "/auth/admin-invitations/verify-code", who="recipient", json={
        "token": token, "challenge_id": first["challenge_id"], "code": first["debug_code"]})
    assert old.status_code == 400
    new = api.call("POST", "/auth/admin-invitations/verify-code", who="recipient", json={
        "token": token, "challenge_id": second["challenge_id"], "code": second["debug_code"]})
    assert new.status_code == 200


def test_wrong_and_expired_otp_no_enrollment(invitation_api):
    api = invitation_api
    data, token = create(api)
    otp = request_otp(api, token)
    wrong = "999999" if otp["debug_code"] != "999999" else "000000"
    for _ in range(settings.otp_max_attempts):
        assert api.call("POST", "/auth/admin-invitations/verify-code", who="recipient", json={
            "token": token, "challenge_id": otp["challenge_id"], "code": wrong}).status_code == 400
    correct_locked = api.call("POST", "/auth/admin-invitations/verify-code", who="recipient", json={
        "token": token, "challenge_id": otp["challenge_id"], "code": otp["debug_code"]})
    assert correct_locked.status_code == 400
    with api.factory() as db:
        assert db.get(AdminInvitation, data["id"]).encrypted_seed == ""


def test_expired_otp_and_mismatched_email_do_not_consume_live_challenge(invitation_api):
    api = invitation_api
    data, token = create(api)
    otp = request_otp(api, token)
    with api.factory() as db:
        challenge = db.get(AdminInvitationChallenge, otp["challenge_id"])
        challenge.expires_at = utcnow() - timedelta(seconds=1)
        db.commit()
    rejected = api.call("POST", "/auth/admin-invitations/verify-code", who="recipient", json={
        "token": token, "challenge_id": otp["challenge_id"], "code": otp["debug_code"]})
    assert rejected.status_code == 400
    with api.factory() as db:
        challenge = db.get(AdminInvitationChallenge, otp["challenge_id"])
        challenge.expires_at = utcnow() + timedelta(minutes=1)
        challenge.email = "different@example.test"
        db.commit()
    rejected = api.call("POST", "/auth/admin-invitations/verify-code", who="recipient", json={
        "token": token, "challenge_id": otp["challenge_id"], "code": otp["debug_code"]})
    assert rejected.status_code == 400
    with api.factory() as db:
        assert db.get(AdminInvitationChallenge, otp["challenge_id"]).consumed_at is None
        assert db.get(AdminInvitation, data["id"]).proof_hash is None


def test_reverified_email_rotates_enrollment_and_rejects_old_proof(invitation_api):
    api = invitation_api
    data, token = create(api)
    enrollment, otp = enroll(api, token)
    with api.factory() as db:
        db.get(AdminInvitationChallenge, otp["challenge_id"]).created_at = utcnow() - timedelta(seconds=61)
        db.commit()
    replacement, _ = enroll(api, token)
    assert replacement["enrollment_token"] != enrollment["enrollment_token"]
    assert replacement["manual_entry_key"] != enrollment["manual_entry_key"]
    assert accept(api, enrollment).status_code == 410
    assert accept(api, replacement).status_code == 200


def test_ordinary_and_invitation_otp_share_email_resend_and_hourly_limits(invitation_api):
    api = invitation_api
    data, token = create(api)
    otp = request_otp(api, token)
    ordinary = api.call("POST", "/auth/request-code", who="recipient", json={"email": data["email"]})
    assert ordinary.status_code == 429
    with api.factory() as db:
        old = utcnow() - timedelta(seconds=70)
        db.get(AdminInvitationChallenge, otp["challenge_id"]).created_at = old
        for index in range(9):
            db.add(AuthChallenge(email=data["email"], code_hash=secret_hash("synthetic:" + str(index)),
                created_at=old, expires_at=utcnow() + timedelta(minutes=1)))
        db.commit()
    assert api.call("POST", "/auth/request-code", who="recipient", json={"email": data["email"]}).status_code == 429
    assert api.call("POST", "/auth/admin-invitations/request-code", who="recipient", json={"token": token}).status_code == 429


def test_parallel_ordinary_and_invitation_otp_obey_one_mailbox_resend_gate(invitation_api):
    api = invitation_api
    data, token = create(api)
    def request_parallel(path):
        payload = {"email": data["email"]} if path == "/auth/request-code" else {"token": token}
        with TestClient(app) as client:
            return client.post("/api/v1" + path, headers={"origin": api.origin}, json=payload).status_code
    with ThreadPoolExecutor(max_workers=2) as pool:
        statuses = list(pool.map(request_parallel, ["/auth/request-code", "/auth/admin-invitations/request-code"]))
    assert sorted(statuses) == [200, 429]
    with api.factory() as db:
        count = sum(db.scalar(select(func.count(model.id)).where(model.email == data["email"]))
                    for model in (AuthChallenge, AdminInvitationChallenge))
        assert count == 1


def test_unavailable_delivery_rolls_back_invitation(invitation_api, monkeypatch):
    api = invitation_api
    monkeypatch.setattr(settings, "email_provider", "none")
    failed = api.call("POST", "/admin/invitations", json={"email": "new-admin@example.test", "full_name": "New Admin"})
    assert failed.status_code == 503
    with api.factory() as db:
        assert db.scalar(select(AdminInvitation)) is None
        assert db.scalar(select(EmailOutbox)) is None


@pytest.mark.parametrize("changes", [{"email": "invalid"}, {"full_name": " "}, {"locale": "de"}])
def test_invite_input_validation_does_not_create_records(invitation_api, changes):
    api = invitation_api
    payload = {"email": "new-admin@example.test", "full_name": "New Admin", "locale": "ru", **changes}
    assert api.call("POST", "/admin/invitations", json=payload).status_code == 422
    with api.factory() as db:
        assert db.scalar(select(AdminInvitation)) is None


@pytest.mark.parametrize("phase", ["before_otp", "after_enroll"])
def test_revocation_clears_proof_seed_challenges_and_queued_mail(invitation_api, phase):
    api = invitation_api
    data, token = create(api)
    enrollment = None
    if phase == "after_enroll":
        enrollment, _ = enroll(api, token)
    with api.factory() as db:
        row = db.scalar(select(EmailOutbox))
        row.status, row.lease_token = "leased", "synthetic-lease"
        db.commit()
    revoked = api.call("DELETE", "/admin/invitations/" + data["id"])
    assert revoked.status_code == 200 and revoked.json()["status"] == "revoked"
    assert api.call("POST", "/auth/admin-invitations/request-code", who="recipient", json={"token": token}).status_code == 410
    if enrollment:
        assert accept(api, enrollment).status_code == 410
    with api.factory() as db:
        invitation = db.get(AdminInvitation, data["id"])
        assert invitation.encrypted_seed == "" and invitation.proof_hash is None
        for row in db.scalars(select(EmailOutbox)).all():
            assert row.status == "failed" and row.encrypted_payload == "" and row.lease_token is None


@pytest.mark.parametrize("reason", ["invite_expired", "proof_expired", "inviter_suspended", "inviter_role", "credential_inactive", "participant_created", "seed_tampered"])
def test_admission_rechecks_live_authority_and_bound_account(invitation_api, reason):
    api = invitation_api
    data, token = create(api)
    enrollment, _ = enroll(api, token)
    with api.factory() as db:
        invitation = db.get(AdminInvitation, data["id"])
        inviter = db.get(User, api.ids["admin"])
        if reason == "invite_expired": invitation.expires_at = utcnow() - timedelta(seconds=1)
        elif reason == "proof_expired": invitation.proof_expires_at = utcnow() - timedelta(seconds=1)
        elif reason == "inviter_suspended": inviter.account_status = "suspended"
        elif reason == "inviter_role": inviter.role = "mentor"
        elif reason == "credential_inactive": db.scalar(select(AdminCredential)).active = False
        elif reason == "participant_created": db.add(User(email=data["email"], role="mentee"))
        elif reason == "seed_tampered": invitation.encrypted_seed = "not-ciphertext"
        db.commit()
    denied = accept(api, enrollment)
    assert denied.status_code in {403, 409, 410, 503}, denied.text
    assert "set-cookie" not in denied.headers
    with api.factory() as db:
        assert db.scalar(select(func.count(User.id)).where(User.email == data["email"], User.role == "admin")) == 0


def test_five_wrong_totp_attempts_clear_pending_secret_without_creating_admin(invitation_api, monkeypatch):
    api = invitation_api
    data, token = create(api)
    enrollment, _ = enroll(api, token)
    monkeypatch.setattr("app.routers.admin_invitations.matching_totp_step", lambda *_: None)
    for _ in range(5):
        response = api.call("POST", "/auth/admin-invitations/accept", who="recipient", json={
            "enrollment_token": enrollment["enrollment_token"], "code": "000000"})
        assert response.status_code == 400
    assert accept(api, enrollment).status_code == 410
    with api.factory() as db:
        row = db.get(AdminInvitation, data["id"])
        assert row.proof_attempts == 5 and row.encrypted_seed == ""
        assert db.scalar(select(User).where(User.email == data["email"])) is None


def test_wrong_token_bad_origin_and_validation_never_echo_secret(invitation_api):
    api = invitation_api
    _, token = create(api)
    invalid_token = token[:-1] + ("a" if token[-1] != "a" else "b")
    rejected = api.call("POST", "/auth/admin-invitations/request-code", who="recipient", json={"token": invalid_token})
    assert rejected.status_code == 400 and invalid_token not in rejected.text
    bad_origin = api.client("recipient").post("/api/v1/auth/admin-invitations/request-code", json={"token": token}, headers={"origin": "https://attacker.example"})
    assert bad_origin.status_code == 403 and token not in bad_origin.text
    malformed = api.call("POST", "/auth/admin-invitations/verify-code", who="recipient", json={"token": token, "challenge_id": "a", "code": "private-input"})
    assert malformed.status_code == 422 and "private-input" not in malformed.text and token not in malformed.text


def test_production_otp_is_queued_and_debug_code_never_returned(invitation_api, monkeypatch):
    api = invitation_api
    _, token = create(api, email="new-admin@gmail.com")
    monkeypatch.setattr(settings, "environment", "production")
    monkeypatch.setattr(settings, "email_provider", "smtp")
    monkeypatch.setattr(settings, "email_from", "synthetic@example.com")
    monkeypatch.setattr(settings, "smtp_host", "smtp.example.test")
    monkeypatch.setattr(settings, "smtp_starttls", True)
    monkeypatch.setattr(settings, "outbox_encryption_key", __import__("cryptography.fernet", fromlist=["Fernet"]).Fernet.generate_key().decode())
    requested = api.call("POST", "/auth/admin-invitations/request-code", who="recipient", json={"token": token})
    assert requested.status_code == 200 and requested.json()["delivery_status"] == "queued"
    assert "debug_code" not in requested.json()
    with api.factory() as db:
        otp_mail = db.scalar(select(EmailOutbox).where(EmailOutbox.dedup_key == "admin-invitation-otp:" + requested.json()["challenge_id"]))
        assert otp_mail.status == "pending" and otp_mail.encrypted_payload


def test_parallel_create_yields_one_pending_invitation(invitation_api):
    api = invitation_api
    cookie = api.client().cookies.get("dc_session")
    def create_parallel(_):
        with TestClient(app) as client:
            client.cookies.set("dc_session", cookie)
            return client.post("/api/v1/admin/invitations", headers={"origin": api.origin}, json={
                "email": "new-admin@example.test", "full_name": "New Administrator"}).status_code
    with ThreadPoolExecutor(max_workers=5) as pool:
        statuses = list(pool.map(create_parallel, range(5)))
    assert statuses.count(201) == 1 and statuses.count(409) == 4
    with api.factory() as db:
        assert db.scalar(select(func.count(AdminInvitation.id))) == 1
        assert db.scalar(select(func.count(EmailOutbox.id))) == 1


def test_parallel_accept_yields_one_admin_one_assured_session(invitation_api):
    api = invitation_api
    data, token = create(api)
    enrollment, _ = enroll(api, token)
    payload = {"enrollment_token": enrollment["enrollment_token"], "code": totp_code(enrollment["manual_entry_key"])}
    def accept_parallel(_):
        with TestClient(app) as client:
            return client.post("/api/v1/auth/admin-invitations/accept", headers={"origin": api.origin}, json=payload).status_code
    with ThreadPoolExecutor(max_workers=5) as pool:
        statuses = list(pool.map(accept_parallel, range(5)))
    assert statuses.count(200) == 1 and statuses.count(410) == 4
    with api.factory() as db:
        user = db.scalar(select(User).where(User.email == data["email"]))
        assert db.scalar(select(func.count(SessionToken.id)).where(SessionToken.user_id == user.id)) == 1
        assert db.scalar(select(func.count(AdminCredential.id)).where(AdminCredential.user_id == user.id)) == 1


def test_invitation_migration_upgrade_downgrade_upgrade_without_existing_data_change(tmp_path, monkeypatch):
    path = tmp_path / "migrations.db"
    monkeypatch.setattr(settings, "database_url", "sqlite:///" + path.as_posix())
    root = Path(__file__).resolve().parents[1]
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "migrations"))
    command.upgrade(config, "0e82eab8e5ef")
    engine = create_engine(settings.database_url)
    with engine.begin() as connection:
        connection.exec_driver_sql("INSERT INTO users (id,email,full_name,role,account_status,intake_open,timezone,preferred_locale,city,bio,expertise,evidence_urls,direction_ids,capacity,profile_completed,created_at) VALUES ('synthetic-admin','synthetic@example.test','Synthetic','admin','active',0,'Asia/Oral','ru','','','','[]','[]',3,1,CURRENT_TIMESTAMP)")
    command.upgrade(config, "head")
    assert {"admin_invitations", "admin_invitation_challenges"} <= set(inspect(engine).get_table_names())
    indices = inspect(engine).get_indexes("admin_invitations")
    assert any(index["name"] == "uq_admin_invitation_pending_email" and index["unique"] for index in indices)
    with engine.connect() as connection:
        assert connection.exec_driver_sql("SELECT role,email FROM users WHERE id='synthetic-admin'").one() == ("admin", "synthetic@example.test")
    command.downgrade(config, "0e82eab8e5ef")
    assert "admin_invitations" not in inspect(engine).get_table_names()
    command.upgrade(config, "head")
    engine.dispose()
