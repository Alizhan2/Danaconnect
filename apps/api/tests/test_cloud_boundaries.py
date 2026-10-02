"""Cloud-facing boundaries tested with disposable DB/files and synthetic senders."""
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
import json

from cryptography.fernet import Fernet
import pytest
from sqlalchemy import func, select

from app import delivery
from app.config import settings
from app.jobs_calendar import wall_to_utc
from app.models import Conversation, ConversationMember, Message, Project, utcnow
from app.models_ai import AIProposal, AIUsageCounter
from app.models_collaboration import PrivateAttachment
from app.models_delivery import EmailOutbox
from app.models_engagement import MessageRead
from app.storage import InvalidAttachment, inspect_attachment


@pytest.fixture
def isolated_mail(monkeypatch):
    monkeypatch.setattr(settings, "environment", "test")
    monkeypatch.setattr(settings, "email_provider", "smtp")
    monkeypatch.setattr(settings, "email_from", "sender@example.test")
    monkeypatch.setattr(settings, "smtp_host", "smtp.example.test")
    monkeypatch.setattr(settings, "smtp_username", "")
    monkeypatch.setattr(settings, "smtp_password", "")
    monkeypatch.setattr(settings, "smtp_starttls", True)
    monkeypatch.setattr(settings, "outbox_encryption_key", Fernet.generate_key().decode())
    monkeypatch.setattr(settings, "outbox_previous_encryption_keys", [])
    monkeypatch.setattr(settings, "outbox_max_attempts", 3)
    # Any accidental provider call fails locally before network access.
    monkeypatch.setattr(delivery, "send_email", lambda *args: pytest.fail("Real delivery is forbidden in isolated tests"))


def test_encrypted_payload_roundtrip_rotation_and_tamper(monkeypatch):
    old_key, new_key = Fernet.generate_key().decode(), Fernet.generate_key().decode()
    monkeypatch.setattr(settings, "outbox_encryption_key", old_key)
    monkeypatch.setattr(settings, "outbox_previous_encryption_keys", [])
    private_text = "Synthetic OTP 123456 recipient@example.test"
    encrypted = delivery.encrypt_text(private_text)
    assert private_text not in encrypted and "123456" not in encrypted
    assert delivery.decrypt_text(encrypted) == private_text
    monkeypatch.setattr(settings, "outbox_encryption_key", new_key)
    monkeypatch.setattr(settings, "outbox_previous_encryption_keys", [old_key])
    assert delivery.decrypt_text(encrypted) == private_text
    monkeypatch.setattr(settings, "outbox_previous_encryption_keys", [])
    with pytest.raises(delivery.DeliveryFailure) as failure:
        delivery.decrypt_text(encrypted)
    assert failure.value.code == "payload_decryption_failed"
    assert failure.value.retryable is False


def test_production_requires_explicit_encryption_key(monkeypatch):
    monkeypatch.setattr(settings, "environment", "production")
    monkeypatch.setattr(settings, "outbox_encryption_key", "")
    with pytest.raises(delivery.DeliveryUnavailable, match="encryption_unconfigured"):
        delivery.encrypt_text("synthetic")


def enqueue_sample(api, *, expires_at=None):
    with api.factory() as db:
        row = delivery.enqueue_email(db, "recipient@example.test", "Synthetic test", "Private synthetic body", dedup_key="isolated-probe", expires_at=expires_at)
        duplicate = delivery.enqueue_email(db, "recipient@example.test", "Synthetic duplicate", "Different body", dedup_key="isolated-probe")
        assert row.id == duplicate.id
        assert "Private synthetic body" not in row.encrypted_payload
        assert "recipient@example.test" not in row.encrypted_payload
        identifier = row.id
        db.commit()
    return identifier


def test_outbox_dedup_success_erases_payload_and_does_not_resend(integrated_api, isolated_mail):
    api = integrated_api
    identifier = enqueue_sample(api)
    calls = []

    def sender(payload, key):
        calls.append((payload, key))
        return "synthetic-provider-receipt"

    assert delivery.process_outbox(api.factory, sender=sender) == {"claimed": 1, "sent": 1, "retried": 0, "failed": 0}
    assert delivery.process_outbox(api.factory, sender=sender)["claimed"] == 0
    assert len(calls) == 1 and calls[0][1] == "isolated-probe"
    with api.factory() as db:
        row = db.get(EmailOutbox, identifier)
        assert row.status == "sent" and row.encrypted_payload == ""
        assert row.sent_at and row.lease_token is None and row.lease_until is None
        assert db.scalar(select(func.count(EmailOutbox.id))) == 1


@pytest.mark.parametrize("retryable, expected_status", [(True, "pending"), (False, "failed")])
def test_outbox_safe_failure_retry_and_terminal_cleanup(integrated_api, isolated_mail, retryable, expected_status):
    api = integrated_api
    identifier = enqueue_sample(api)

    def sender(payload, key):
        raise delivery.DeliveryFailure("smtp_response_451", retryable=retryable)

    summary = delivery.process_outbox(api.factory, limit=1, sender=sender)
    assert summary["retried" if retryable else "failed"] == 1
    with api.factory() as db:
        row = db.get(EmailOutbox, identifier)
        assert row.status == expected_status and row.attempts == 1
        assert row.last_error_code == "smtp_response_451"
        assert row.lease_token is None and row.lease_until is None
        assert bool(row.encrypted_payload) is retryable
        if retryable:
            assert row.next_attempt_at > utcnow()


def test_expired_outbox_never_calls_sender_and_erases_payload(integrated_api, isolated_mail):
    api = integrated_api
    identifier = enqueue_sample(api, expires_at=utcnow() - timedelta(minutes=1))
    summary = delivery.process_outbox(api.factory, sender=lambda *args: pytest.fail("Expired mail must not be sent"))
    assert summary["failed"] == 1 and summary["sent"] == 0
    with api.factory() as db:
        row = db.get(EmailOutbox, identifier)
        assert row.status == "failed" and row.last_error_code == "message_expired"
        assert row.encrypted_payload == ""


@pytest.mark.parametrize("filename, content_type, data", [
    ("../escape.txt", "text/plain", b"hello"),
    ("fake.pdf", "application/pdf", b"ordinary text"),
    ("nul.txt", "text/plain", b"hello\x00world"),
    ("empty.txt", "text/plain", b""),
    ("code.exe", "application/octet-stream", b"MZsynthetic"),
    ("active.pdf", "application/pdf", b"%PDF-1.7 /JavaScript %%EOF"),
])
def test_attachment_validation_rejects_unsafe_inputs(filename, content_type, data):
    with pytest.raises(InvalidAttachment):
        inspect_attachment(filename, content_type, data)


def test_private_attachment_access_integrity_and_delete(integrated_api, monkeypatch, tmp_path):
    api = integrated_api
    monkeypatch.setattr(settings, "storage_provider", "local")
    monkeypatch.setattr(settings, "private_upload_dir", str(tmp_path / "private"))
    with api.factory() as db:
        project = Project(owner_id=api.ids["mentee"], direction_id=api.ids["direction"], title="Synthetic file project", problem="Synthetic problem", description="Synthetic description")
        db.add(project)
        db.commit()
        project_id = project.id
    body = b"Isolated private attachment"
    uploaded = api.call("POST", f"/projects/{project_id}/attachments", "mentee", files={"file": ("sample.txt", body, "text/plain")})
    assert uploaded.status_code == 201, uploaded.text
    identifier = uploaded.json()["id"]
    assert "storage_key" not in uploaded.json()
    assert api.call("GET", f"/attachments/{identifier}/download", "stranger").status_code == 404
    downloaded = api.call("GET", f"/attachments/{identifier}/download", "mentee")
    assert downloaded.status_code == 200 and downloaded.content == body
    assert downloaded.headers["content-security-policy"] == "sandbox"
    assert downloaded.headers["x-content-type-options"] == "nosniff"
    with api.factory() as db:
        attachment = db.get(PrivateAttachment, identifier)
        path = tmp_path / "private" / attachment.storage_key
        path.write_bytes(b"X" * len(body))
    assert api.call("GET", f"/attachments/{identifier}/download", "mentee").status_code == 503
    assert api.call("DELETE", f"/attachments/{identifier}", "stranger").status_code == 404
    assert api.call("DELETE", f"/attachments/{identifier}", "mentee").status_code == 200
    assert not path.exists()
    assert api.call("GET", f"/attachments/{identifier}/download", "mentee").status_code == 404


def test_dst_nonexistent_and_ambiguous_wall_times_are_explicit():
    zone = ZoneInfo("Europe/Berlin")
    assert wall_to_utc(datetime(2026, 3, 29, 2, 30), zone, "first") is None
    ambiguous = datetime(2026, 10, 25, 2, 30)
    first, second = wall_to_utc(ambiguous, zone, "first"), wall_to_utc(ambiguous, zone, "second")
    assert second - first == timedelta(hours=1)


def test_weekly_calendar_role_generation_idempotence_and_disable(integrated_api):
    api = integrated_api
    day = utcnow().astimezone(ZoneInfo("Asia/Oral")).date() + timedelta(days=1)
    payload = {"weekday": day.weekday(), "start_time": "10:00", "end_time": "11:00", "timezone": "Asia/Oral", "slot_minutes": 30, "starts_on": day.isoformat(), "horizon_weeks": 2}
    assert api.call("POST", "/availability-rules", "mentee", json=payload).status_code == 403
    created = api.call("POST", "/availability-rules", "mentor", json=payload)
    assert created.status_code == 201, created.text
    assert created.json()["generation"]["created"] == 4
    identifier = created.json()["rule"]["id"]
    regenerated = api.call("POST", f"/availability-rules/{identifier}/regenerate", "mentor")
    assert regenerated.status_code == 200 and regenerated.json()["generation"]["created"] == 0
    disabled = api.call("DELETE", f"/availability-rules/{identifier}", "mentor")
    assert disabled.status_code == 200 and disabled.json()["cancelled_free"] == 4
    assert api.call("POST", f"/availability-rules/{identifier}/regenerate", "mentor").status_code == 409


def test_message_receipts_are_member_only_incoming_only_and_idempotent(integrated_api):
    api = integrated_api
    with api.factory() as db:
        conversation = Conversation()
        db.add(conversation)
        db.flush()
        db.add_all([ConversationMember(conversation_id=conversation.id, user_id=api.ids[who]) for who in ("mentor", "mentee")])
        incoming = Message(conversation_id=conversation.id, sender_id=api.ids["mentor"], body="Synthetic incoming")
        own = Message(conversation_id=conversation.id, sender_id=api.ids["mentee"], body="Synthetic own message")
        db.add_all([incoming, own])
        db.commit()
        conversation_id, incoming_id, own_id = conversation.id, incoming.id, own.id
    assert api.call("GET", "/messages/unread-summary", "mentee").json()["total_unread"] == 1
    assert api.call("GET", "/messages/unread-summary", "stranger").json()["total_unread"] == 0
    path = f"/conversations/{conversation_id}/read"
    assert api.call("POST", path, "stranger", json={"message_ids": [incoming_id]}).status_code == 404
    assert api.call("POST", path, "mentee", json={"message_ids": [own_id]}).status_code == 422
    assert api.call("POST", path, "mentee", json={"message_ids": [incoming_id, incoming_id]}).status_code == 422
    for _ in range(2):
        marked = api.call("POST", path, "mentee", json={"message_ids": [incoming_id]})
        assert marked.status_code == 200 and marked.json()["summary"]["total_unread"] == 0
    with api.factory() as db:
        assert db.scalar(select(func.count(MessageRead.id))) == 1


def test_disabled_ai_has_no_provider_call_or_usage_side_effects(integrated_api, monkeypatch):
    api = integrated_api
    monkeypatch.setattr(settings, "ai_enabled", False)
    monkeypatch.setattr(settings, "ai_api_key", "")
    from app.services import ai
    monkeypatch.setattr(ai, "provider_response", lambda **kwargs: pytest.fail("Disabled AI must never contact provider"))
    status = api.call("GET", "/ai/status", "mentee")
    assert status.status_code == 200 and status.json()["available"] is False
    result = api.call("POST", "/ai/structure", "mentee", json={"consent": True, "text": "A synthetic project idea to organize"})
    assert result.status_code == 503
    recommended = api.call("POST", "/ai/mentor-recommendations", "mentee", json={"consent": True, "direction_id": api.ids["direction"], "goal": "A synthetic mentoring goal"})
    assert recommended.status_code == 503
    with api.factory() as db:
        assert db.scalar(select(func.count(AIProposal.id))) == 0
        assert db.scalar(select(func.count(AIUsageCounter.id))) == 0


def test_unauthorized_scheduler_and_untrusted_origin_do_not_execute(integrated_api, monkeypatch):
    api = integrated_api
    from app.routers import jobs
    monkeypatch.setattr(settings, "cron_secret", "synthetic-cron-secret-never-deployed-0123456789")
    monkeypatch.setattr(jobs, "run_once", lambda: pytest.fail("Unauthorized request must not execute worker"))
    assert api.call("GET", "/internal/jobs").status_code == 401
    rejected = api.client().post("/api/v1/auth/request-code", json={}, headers={"origin": "https://invalid.example"})
    assert rejected.status_code == 403
    assert rejected.headers["x-content-type-options"] == "nosniff"
    assert rejected.headers["cache-control"] == "no-store"
