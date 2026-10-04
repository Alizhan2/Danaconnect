"""Mail user stories with disposable DB data and a fake SMTP transport.

No real mailbox, provider credential, Google account or network call is used.
"""
from datetime import datetime, timedelta, timezone
import hashlib
import json
import re
import smtplib
import ssl

from cryptography.fernet import Fernet
import pytest
from sqlalchemy import event, func, select

from app import delivery, jobs_calendar
from app.booking_lifecycle import cancel_reservation
from app.config import settings
from app.models import AuthChallenge, Booking, Notification, Slot, User, utcnow
from app.models_calendar import BookingReminder
from app.models_delivery import EmailOutbox
from app.routers import identity


@pytest.fixture
def mail_transport(monkeypatch):
    """Configuration and protocol are synthetic, including authentication."""
    for key, value in {
        "environment": "test", "email_provider": "smtp",
        "email_from": "DanaConnect Team <team@example.test>",
        "smtp_host": "smtp.example.test", "smtp_port": 587,
        "smtp_tls": False, "smtp_starttls": True,
        "smtp_username": "team@example.test", "smtp_password": "synthetic-password",
        "outbox_encryption_key": Fernet.generate_key().decode(),
        "outbox_previous_encryption_keys": [], "outbox_max_attempts": 3,
        "outbox_lease_seconds": 60, "frontend_url": "https://platform.example.test",
    }.items():
        monkeypatch.setattr(settings, key, value)
    events, messages, behaviours = [], [], {}

    class FakeSMTP:
        def __init__(self, host, port, *, timeout, context=None):
            assert host == "smtp.example.test" and timeout == 10
            events.append(("connect_ssl" if context is not None else "connect", port))
            if context is not None:
                assert context.verify_mode == ssl.CERT_REQUIRED and context.check_hostname

        def __enter__(self):
            return self

        def __exit__(self, *_):
            events.append(("close",))

        def starttls(self, *, context):
            assert context.verify_mode == ssl.CERT_REQUIRED and context.check_hostname
            events.append(("starttls",))
            if behaviours.get("tls_error"):
                raise behaviours["tls_error"]

        def login(self, username, password):
            assert username == "team@example.test" and password == "synthetic-password"
            events.append(("login",))

        def send_message(self, message):
            events.append(("send",))
            messages.append(message)
            if behaviours.get("send_error"):
                raise behaviours["send_error"]
            return behaviours.get("refused", {})

    monkeypatch.setattr(delivery.smtplib, "SMTP", FakeSMTP)
    monkeypatch.setattr(delivery.smtplib, "SMTP_SSL", FakeSMTP)
    monkeypatch.setattr(delivery.httpx, "post", lambda *args, **kwargs: pytest.fail("HTTP provider forbidden"))
    return events, messages, behaviours


def payload():
    return {"recipient": "participant@example.test", "subject": "Synthetic sign-in",
            "text": "Synthetic private sign-in code: 123456", "locale": "en"}


def queue(api, *, key="mail-scenario", expires_at=None):
    with api.factory() as db:
        item = delivery.enqueue_email(db, **{
            "recipient": payload()["recipient"], "subject": payload()["subject"],
            "text": payload()["text"], "dedup_key": key, "expires_at": expires_at,
        })
        db.commit()
        return item.id


def test_smtp_starttls_precedes_login_and_uses_configured_sender(mail_transport):
    events, messages, _ = mail_transport
    receipt = delivery.send_email(payload(), "synthetic-mail-key")
    assert [event[0] for event in events] == ["connect", "starttls", "login", "send", "close"]
    assert messages[0]["From"] == settings.email_from
    assert messages[0]["To"] == "participant@example.test"
    assert messages[0].get_content().strip() == payload()["text"]
    assert "synthetic-password" not in messages[0].as_string()
    expected = "<dc-" + hashlib.sha256(b"synthetic-mail-key").hexdigest() + "@danaconnect.invalid>"
    assert receipt == expected == messages[0]["Message-ID"]
    assert delivery.send_email(payload(), "synthetic-mail-key") == expected
    assert delivery.send_email(payload(), "different-synthetic-key") != expected


def test_smtp_implicit_tls_is_verified_before_login(mail_transport, monkeypatch):
    events, _, _ = mail_transport
    monkeypatch.setattr(settings, "smtp_tls", True)
    monkeypatch.setattr(settings, "smtp_starttls", False)
    monkeypatch.setattr(settings, "smtp_port", 465)
    delivery.send_email(payload(), "implicit-tls")
    assert events == [("connect_ssl", 465), ("login",), ("send",), ("close",)]


def test_failed_tls_never_sends_or_authenticates(mail_transport):
    events, _, behaviours = mail_transport
    behaviours["tls_error"] = ssl.SSLError("synthetic-password participant@example.test 123456")
    with pytest.raises(delivery.DeliveryFailure) as error:
        delivery.send_email(payload(), "failed-tls")
    assert str(error.value) == "smtp_connection" and error.value.retryable
    assert "login" not in [event[0] for event in events]
    assert "send" not in [event[0] for event in events]


@pytest.mark.parametrize("status,retryable", [(421, True), (451, True), (535, False), (550, False)])
def test_smtp_response_codes_are_sanitized(mail_transport, caplog, status, retryable):
    _, _, behaviours = mail_transport
    private = "synthetic-password participant@example.test 123456"
    behaviours["send_error"] = smtplib.SMTPResponseException(status, private.encode())
    with pytest.raises(delivery.DeliveryFailure) as error:
        delivery.send_email(payload(), "response-failure")
    assert str(error.value) == f"smtp_response_{status}"
    assert error.value.retryable is retryable
    assert private not in str(error.value) + caplog.text
    assert "123456" not in str(error.value) + caplog.text
    assert "participant@example.test" not in str(error.value) + caplog.text


@pytest.mark.parametrize("raises", [False, True])
@pytest.mark.parametrize("status,retryable", [(450, True), (550, False)])
def test_single_recipient_refusal_retries_only_transient_codes(mail_transport, raises, status, retryable):
    _, _, behaviours = mail_transport
    refusals = {"participant@example.test": (status, b"private rejected recipient details")}
    if raises:
        behaviours["send_error"] = smtplib.SMTPRecipientsRefused(refusals)
    else:
        behaviours["refused"] = refusals
    with pytest.raises(delivery.DeliveryFailure) as error:
        delivery.send_email(payload(), "recipient-refusal")
    assert str(error.value) == "smtp_recipient_refused"
    assert error.value.retryable is retryable


def test_otp_api_expiry_matches_outbox_and_delayed_code_never_dispatches(integrated_api, mail_transport, monkeypatch):
    api = integrated_api
    monkeypatch.setattr(settings, "auth_debug_code", False)
    monkeypatch.setattr(identity, "dispatch_email_now", lambda *_: "queued")
    requested = api.call("POST", "/auth/request-code", json={"email": "new-admin@example.test", "locale": "en"})
    assert requested.status_code == 200 and requested.json()["delivery_status"] == "queued"
    assert "debug_code" not in requested.json()
    with api.factory() as db:
        challenge = db.get(AuthChallenge, requested.json()["challenge_id"])
        item = db.scalar(select(EmailOutbox))
        assert item.dedup_key == "auth-otp:" + challenge.id
        assert item.expires_at == challenge.expires_at
        code = re.search(r"\b\d{6}\b", json.loads(delivery.decrypt_text(item.encrypted_payload))["text"]).group()
        expiration, item_id = challenge.expires_at, item.id
    monkeypatch.setattr(delivery, "utcnow", lambda: expiration)
    monkeypatch.setattr(identity, "utcnow", lambda: expiration)
    assert delivery.process_outbox(api.factory, sender=lambda *args: pytest.fail("Expired OTP was dispatched"))["failed"] == 1
    rejected = api.call("POST", "/auth/verify-code", json={"challenge_id": requested.json()["challenge_id"], "code": code})
    assert rejected.status_code == 400 and "dc_session" not in rejected.cookies
    with api.factory() as db:
        item = db.get(EmailOutbox, item_id)
        assert item.last_error_code == "message_expired" and item.encrypted_payload == ""


def test_otp_sends_before_response_after_commit_and_leaves_other_mail_queued(integrated_api, mail_transport, monkeypatch):
    api = integrated_api
    _, messages, _ = mail_transport
    other_id = queue(api, key="unrelated-older-message")
    monkeypatch.setattr(settings, "auth_debug_code", False)
    engine = api.factory.kw["bind"]
    transactions = set()
    def begin(connection):
        transactions.add(connection)
    def finish(connection):
        transactions.discard(connection)
    event.listen(engine, "begin", begin)
    event.listen(engine, "commit", finish)
    event.listen(engine, "rollback", finish)
    original_sender = delivery.send_email
    def sender(payload, key):
        assert not transactions, "SMTP must not hold a database transaction"
        with api.factory() as check:
            challenge_id = key.removeprefix("auth-otp:")
            assert check.get(AuthChallenge, challenge_id) is not None
        assert not transactions
        return original_sender(payload, key)
    monkeypatch.setattr(delivery, "send_email", sender)
    try:
        response = api.call("POST", "/auth/request-code", json={"email": "fast@example.test", "locale": "en"})
        assert response.status_code == 200 and response.json()["delivery_status"] == "sent"
        assert "debug_code" not in response.json()
        assert len(messages) == 1 and messages[0]["To"] == "fast@example.test"
        code = re.search(r"\b\d{6}\b", messages[0].get_content()).group()
        with api.factory() as db:
            item = db.scalar(select(EmailOutbox).where(EmailOutbox.dedup_key == "auth-otp:" + response.json()["challenge_id"]))
            assert item.status == "sent" and item.attempts == 1 and item.encrypted_payload == ""
            item_id = item.id
            assert db.get(EmailOutbox, other_id).status == "pending"
        assert delivery.process_outbox(api.factory, limit=1, outbox_id=item_id)["claimed"] == 0
        verified = api.call("POST", "/auth/verify-code", json={"challenge_id": response.json()["challenge_id"], "code": code})
        assert verified.status_code == 200
    finally:
        event.remove(engine, "begin", begin)
        event.remove(engine, "commit", finish)
        event.remove(engine, "rollback", finish)


def test_otp_transient_failure_stays_queued_for_worker_recovery(integrated_api, mail_transport, monkeypatch):
    api = integrated_api
    _, messages, behaviours = mail_transport
    monkeypatch.setattr(settings, "auth_debug_code", False)
    behaviours["send_error"] = smtplib.SMTPDataError(451, b"synthetic private body")
    response = api.call("POST", "/auth/request-code", json={"email": "retry@example.test"})
    assert response.status_code == 200 and response.json()["delivery_status"] == "queued"
    with api.factory() as db:
        item = db.scalar(select(EmailOutbox))
        assert item.status == "pending" and item.attempts == 1 and item.encrypted_payload
        retry_at = item.next_attempt_at
    assert delivery.process_outbox(api.factory)["claimed"] == 0
    behaviours.pop("send_error")
    monkeypatch.setattr(delivery, "utcnow", lambda: retry_at)
    assert delivery.process_outbox(api.factory)["sent"] == 1
    assert len(messages) == 2 and messages[0]["Message-ID"] == messages[1]["Message-ID"]


def test_otp_permanent_failure_is_not_reported_as_sent(integrated_api, mail_transport, monkeypatch):
    api = integrated_api
    monkeypatch.setattr(settings, "auth_debug_code", False)
    mail_transport[2]["send_error"] = smtplib.SMTPDataError(550, b"private refused body")
    response = api.call("POST", "/auth/request-code", json={"email": "refused@example.test"})
    assert response.status_code == 503
    assert "private refused body" not in response.text and "debug_code" not in response.text
    with api.factory() as db:
        item = db.scalar(select(EmailOutbox))
        assert item.status == "failed" and item.encrypted_payload == "" and item.attempts == 1


def test_replaced_ordinary_code_cancels_pending_mail(integrated_api, mail_transport, monkeypatch):
    api = integrated_api
    monkeypatch.setattr(settings, "auth_debug_code", False)
    monkeypatch.setattr(identity, "dispatch_email_now", lambda *_: "queued")
    first = api.call("POST", "/auth/request-code", json={"email": "replace@example.test"})
    assert first.status_code == 200
    with api.factory() as db:
        old = db.get(AuthChallenge, first.json()["challenge_id"])
        old.created_at = utcnow() - timedelta(seconds=61)
        db.commit()
    second = api.call("POST", "/auth/request-code", json={"email": "replace@example.test"})
    assert second.status_code == 200
    with api.factory() as db:
        old = db.scalar(select(EmailOutbox).where(EmailOutbox.dedup_key == "auth-otp:" + first.json()["challenge_id"]))
        assert old.status == "failed" and old.last_error_code == "otp_replaced" and old.encrypted_payload == ""
        assert db.get(AuthChallenge, first.json()["challenge_id"]).consumed_at
        assert db.scalar(select(EmailOutbox).where(EmailOutbox.dedup_key == "auth-otp:" + second.json()["challenge_id"])).status == "pending"


def test_immediate_delivery_requires_commit_and_does_not_steal_active_lease(integrated_api, mail_transport):
    api = integrated_api
    item_id = queue(api)
    with api.factory() as db:
        row = db.get(EmailOutbox, item_id)
        with pytest.raises(ValueError, match="committed"):
            delivery.dispatch_email_now(db, item_id)
        row.status, row.lease_token, row.lease_until = "leased", "existing-worker", utcnow() + timedelta(seconds=60)
        db.commit()
        assert delivery.dispatch_email_now(db, item_id) == "queued"
    assert not mail_transport[1]


def test_immediate_delivery_setup_failure_preserves_pending_mail(integrated_api, mail_transport, monkeypatch, caplog):
    api = integrated_api
    item_id = queue(api)
    def broken(*_, **__):
        raise RuntimeError("123456 private@example.test secret")
    monkeypatch.setattr(delivery, "process_outbox", broken)
    with api.factory() as db:
        assert delivery.dispatch_email_now(db, item_id) == "queued"
        assert db.get(EmailOutbox, item_id).status == "pending"
    assert "123456" not in caplog.text and "private@example.test" not in caplog.text and "secret" not in caplog.text


def test_transient_smtp_retry_waits_then_succeeds_with_same_message_id(integrated_api, mail_transport, monkeypatch):
    api = integrated_api
    _, messages, behaviours = mail_transport
    item_id = queue(api)
    behaviours["send_error"] = smtplib.SMTPDataError(451, b"synthetic-password 123456")
    first = delivery.process_outbox(api.factory, limit=1)
    assert first == {"claimed": 1, "sent": 0, "retried": 1, "failed": 0}
    with api.factory() as db:
        item = db.get(EmailOutbox, item_id)
        retry_at = item.next_attempt_at
        assert item.last_error_code == "smtp_response_451" and item.encrypted_payload
    assert delivery.process_outbox(api.factory)["claimed"] == 0
    behaviours.pop("send_error")
    monkeypatch.setattr(delivery, "utcnow", lambda: retry_at)
    assert delivery.process_outbox(api.factory) == {"claimed": 1, "sent": 1, "retried": 0, "failed": 0}
    assert messages[0]["Message-ID"] == messages[1]["Message-ID"]
    with api.factory() as db:
        item = db.get(EmailOutbox, item_id)
        assert item.attempts == 2 and item.status == "sent" and item.encrypted_payload == ""


def test_repeated_transient_smtp_failure_stops_at_attempt_limit(integrated_api, mail_transport, monkeypatch):
    api = integrated_api
    _, messages, behaviours = mail_transport
    item_id = queue(api)
    clock = [utcnow() + timedelta(seconds=1)]
    monkeypatch.setattr(delivery, "utcnow", lambda: clock[0])
    behaviours["send_error"] = smtplib.SMTPDataError(451, b"synthetic private server body")
    for attempt in range(1, settings.outbox_max_attempts + 1):
        summary = delivery.process_outbox(api.factory, limit=1)
        assert summary["retried" if attempt < settings.outbox_max_attempts else "failed"] == 1
        with api.factory() as db:
            item = db.get(EmailOutbox, item_id)
            assert item.attempts == attempt and item.last_error_code == "smtp_response_451"
            clock[0] = item.next_attempt_at
    assert delivery.process_outbox(api.factory)["claimed"] == 0
    assert len(messages) == settings.outbox_max_attempts
    assert len({message["Message-ID"] for message in messages}) == 1
    with api.factory() as db:
        item = db.get(EmailOutbox, item_id)
        assert item.status == "failed" and item.encrypted_payload == ""


def test_unexpired_lease_prevents_other_worker_dispatch(integrated_api, mail_transport):
    api = integrated_api
    item_id = queue(api)

    def slow_sender(*_):
        # A second session can read/write while delivery is outside its claim
        # transaction, and another worker cannot claim this unexpired lease.
        with api.factory() as db:
            item = db.get(EmailOutbox, item_id)
            assert item.status == "leased" and item.lease_token and item.attempts == 1
        assert delivery.process_outbox(api.factory, sender=lambda *_: pytest.fail("Active lease stolen"))["claimed"] == 0
        return "first-worker-receipt"

    assert delivery.process_outbox(api.factory, sender=slow_sender)["sent"] == 1


def test_expired_lease_takeover_keeps_newer_receipt(integrated_api, mail_transport, monkeypatch):
    api = integrated_api
    item_id = queue(api)
    clock = [utcnow() + timedelta(seconds=1)]
    monkeypatch.setattr(delivery, "utcnow", lambda: clock[0])
    calls = []

    def new_sender(_, key):
        calls.append(key)
        return "newer-worker-receipt"

    def slow_sender(_, key):
        calls.append(key)
        clock[0] += timedelta(seconds=settings.outbox_lease_seconds + 1)
        assert delivery.process_outbox(api.factory, sender=new_sender)["sent"] == 1
        return "older-worker-receipt"

    first = delivery.process_outbox(api.factory, sender=slow_sender)
    assert first == {"claimed": 1, "sent": 0, "retried": 0, "failed": 0}
    # SMTP can accept both sends when a worker outlives its lease; the same key
    # permits a stable Message-ID, and the old completion cannot overwrite.
    assert calls == ["mail-scenario", "mail-scenario"]
    with api.factory() as db:
        item = db.get(EmailOutbox, item_id)
        assert item.provider_message_id == "newer-worker-receipt" and item.attempts == 2


def meeting(api, now, *, offset=timedelta(minutes=40), status="scheduled"):
    with api.factory() as db:
        slot = Slot(mentor_id=api.ids["mentor"], starts_at=now + offset,
                    ends_at=now + offset + timedelta(minutes=30), status="booked", timezone="Asia/Oral")
        db.add(slot)
        db.flush()
        booking = Booking(slot_id=slot.id, mentor_id=api.ids["mentor"], mentee_id=api.ids["mentee"],
                          status=status, meeting_url="https://private.example.test/old-secret-meeting")
        db.add(booking)
        db.commit()
        return booking.id


@pytest.mark.parametrize("locale,zone,expected,title_part", [
    ("ru", "Asia/Oral", "2026-10-04 15:00 · Asia/Oral", "Напоминание"),
    ("kk", "Asia/Almaty", "2026-10-04 15:00 · Asia/Almaty", "еске салу"),
    ("en", "Europe/Berlin", "2026-10-04 12:00 · Europe/Berlin", "meeting reminder"),
])
@pytest.mark.parametrize("kind", ["1h", "24h"])
def test_reminder_copy_uses_recipient_language_and_timezone(locale, zone, expected, title_part, kind, mail_transport):
    person = User(full_name="Synthetic participant", preferred_locale=locale, timezone=zone)
    other = User(full_name="Synthetic mentor")
    slot = Slot(starts_at=datetime(2026, 10, 4, 10, tzinfo=timezone.utc), timezone="Pacific/Auckland")
    booking = Booking(meeting_url="https://private.example.test/old-secret-meeting")
    title, body, rendered_locale = jobs_calendar.reminder_content(person, other, slot, booking, kind)
    assert title_part in title and expected in body and "Synthetic mentor" in body
    assert rendered_locale == locale
    assert body.endswith("https://platform.example.test/calendar")
    assert booking.meeting_url not in body


@pytest.mark.parametrize("offset,kind", [(timedelta(hours=23, minutes=30), "24h"), (timedelta(minutes=40), "1h")])
def test_reminder_worker_queues_each_party_once_and_dispatches_once(integrated_api, mail_transport, monkeypatch, offset, kind):
    api = integrated_api
    now = utcnow()
    booking_id = meeting(api, now, offset=offset)
    with api.factory() as db:
        db.get(User, api.ids["mentor"]).preferred_locale = "kk"
        db.get(User, api.ids["mentee"]).preferred_locale = "en"
        db.get(User, api.ids["mentee"]).timezone = "Europe/Berlin"
        db.commit()
    monkeypatch.setattr(jobs_calendar, "utcnow", lambda: now)
    first = jobs_calendar.run_once(api.factory)
    second = jobs_calendar.run_once(api.factory)
    assert first["reminders"] == {"processed": 1, "email_queued": 2, "in_app_only": 0, "errors": 0}
    assert first["email"]["sent"] == 2
    assert second["reminders"]["processed"] == 0 and second["email"]["claimed"] == 0
    with api.factory() as db:
        reminders = db.scalars(select(BookingReminder)).all()
        assert len(reminders) == 2 and {row.kind for row in reminders} == {kind}
        assert {row.dedup_key for row in reminders} == {
            f"booking-reminder:{booking_id}:{api.ids[who]}:{kind}" for who in ("mentor", "mentee")}
        assert db.scalar(select(func.count(Notification.id))) == 2
        assert all(item.status == "sent" and item.encrypted_payload == "" for item in db.scalars(select(EmailOutbox)))
    _, messages, _ = mail_transport
    assert len(messages) == 2 and {str(item["From"]) for item in messages} == {settings.email_from}


def test_canceled_meeting_does_not_queue_reminders(integrated_api, mail_transport):
    api = integrated_api
    now = utcnow()
    meeting(api, now, status="cancelled")
    assert jobs_calendar.enqueue_reminders(api.factory, now=now)["processed"] == 0
    with api.factory() as db:
        assert db.scalar(select(func.count(EmailOutbox.id))) == 0
        assert db.scalar(select(func.count(BookingReminder.id))) == 0


@pytest.mark.parametrize("leased", [False, True])
def test_cancel_endpoint_revokes_queued_and_leased_reminders(integrated_api, mail_transport, leased):
    api = integrated_api
    # Authenticate before switching from debug fixtures to a real outbox story.
    client = api.client("mentee")
    now = utcnow()
    booking_id = meeting(api, now)
    assert jobs_calendar.enqueue_reminders(api.factory, now=now)["email_queued"] == 2
    if leased:
        with api.factory() as db:
            for item in db.scalars(select(EmailOutbox)):
                item.status, item.lease_token = "leased", "synthetic-lease"
                item.lease_until = now + timedelta(minutes=1)
            db.commit()
    response = client.post(f"/api/v1/bookings/{booking_id}/cancel", headers={"origin": api.origin})
    assert response.status_code == 200, response.text
    assert delivery.process_outbox(api.factory, sender=lambda *_: pytest.fail("Canceled reminder sent"))["claimed"] == 0
    with api.factory() as db:
        items = db.scalars(select(EmailOutbox)).all()
        assert len(items) == 2
        assert all(item.status == "failed" and item.last_error_code == "booking_cancelled"
                   and item.encrypted_payload == "" and item.lease_token is None and item.lease_until is None for item in items)


def test_cancel_after_claim_before_send_revalidates_current_lease(integrated_api, mail_transport, monkeypatch):
    api = integrated_api
    now = utcnow()
    booking_id = meeting(api, now)
    jobs_calendar.enqueue_reminders(api.factory, now=now)
    original_decrypt = delivery.decrypt_text

    def cancel_between_claim_and_send(encrypted):
        body = original_decrypt(encrypted)
        with api.factory() as db:
            cancel_reservation(db, db.get(Booking, booking_id))
            db.commit()
        return body

    monkeypatch.setattr(delivery, "decrypt_text", cancel_between_claim_and_send)
    summary = delivery.process_outbox(api.factory, sender=lambda *_: pytest.fail("Revoked lease was sent"))
    assert summary == {"claimed": 1, "sent": 0, "retried": 0, "failed": 0}
    with api.factory() as db:
        assert all(item.status == "failed" and item.last_error_code == "booking_cancelled" for item in db.scalars(select(EmailOutbox)))


def test_reminder_delayed_past_start_expires_without_provider_call(integrated_api, mail_transport, monkeypatch):
    api = integrated_api
    now = utcnow()
    booking_id = meeting(api, now)
    assert jobs_calendar.enqueue_reminders(api.factory, now=now)["email_queued"] == 2
    with api.factory() as db:
        starts_at = db.get(Slot, db.get(Booking, booking_id).slot_id).starts_at
        assert {item.expires_at for item in db.scalars(select(EmailOutbox))} == {starts_at}
    monkeypatch.setattr(delivery, "utcnow", lambda: starts_at)
    summary = delivery.process_outbox(api.factory, sender=lambda *_: pytest.fail("Late reminder sent"))
    assert summary["failed"] == 2 and summary["sent"] == 0


def test_outbox_expiring_after_claim_before_provider_is_not_sent(integrated_api, mail_transport, monkeypatch):
    api = integrated_api
    expiry = utcnow() + timedelta(minutes=1)
    item_id = queue(api, expires_at=expiry)
    clock = [utcnow() + timedelta(seconds=1)]
    original_decrypt = delivery.decrypt_text
    monkeypatch.setattr(delivery, "utcnow", lambda: clock[0])

    def delayed_decrypt(encrypted):
        content = original_decrypt(encrypted)
        clock[0] = expiry
        return content

    monkeypatch.setattr(delivery, "decrypt_text", delayed_decrypt)
    result = delivery.process_outbox(api.factory, sender=lambda *_: pytest.fail("Expired current lease sent"))
    assert result == {"claimed": 1, "sent": 0, "retried": 0, "failed": 1}
    with api.factory() as db:
        item = db.get(EmailOutbox, item_id)
        assert item.last_error_code == "message_expired" and item.encrypted_payload == ""


@pytest.mark.parametrize("locale", ["ru", "kk", "en"])
def test_admin_invitation_copy_is_explicit_about_full_access_expiry_and_mfa(locale):
    from app.routers.admin_invitations import invitation_email
    link = "https://platform.example.test/admin/invitation#token=synthetic-preview-token"
    title, body = invitation_email("Synthetic Admin", link, locale)
    assert "DanaConnect" in title and "Synthetic Admin" in body and link in body
    assert "7" in body and "MFA" in body and "QR" in body
    assert {"ru": "полными правами", "kk": "толық әкімші", "en": "full administrator"}[locale] in body
