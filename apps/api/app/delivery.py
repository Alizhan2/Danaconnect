"""Encrypted transactional email outbox. SMTP delivery is at least once.

Provider calls happen only after commits, never in database transactions.
Resend receives a stable idempotency key; SMTP receives a stable Message-ID but
cannot promise provider-side deduplication after a send/acknowledgement crash.
"""
import base64
import hashlib
import json
import logging
import smtplib
import ssl
from datetime import timedelta
from email.message import EmailMessage
from time import perf_counter
from uuid import uuid4

import httpx
from cryptography.fernet import Fernet, InvalidToken, MultiFernet
from email_validator import EmailNotValidError, validate_email
from sqlalchemy import and_, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from app.config import settings
from app.database import SessionLocal
from app.models import utcnow
from app.models_delivery import EmailOutbox


class DeliveryUnavailable(RuntimeError):
    pass


class DeliveryFailure(RuntimeError):
    def __init__(self, code: str, retryable: bool = True):
        super().__init__(code)
        self.code, self.retryable = code, retryable


def _recipient_refusal_retryable(refused: dict) -> bool:
    # A single recipient refusal normally raises SMTPRecipientsRefused rather
    # than returning from send_message. Keep addresses and server bodies out of
    # failures; only numeric response classes affect the retry decision.
    codes = [response[0] for response in refused.values()
             if isinstance(response, (tuple, list)) and response
             and isinstance(response[0], int)]
    return not codes or any(400 <= code < 500 for code in codes)


def cipher():
    key = settings.outbox_encryption_key
    if not key:
        if settings.environment == "production":
            raise DeliveryUnavailable("encryption_unconfigured")
        key = base64.urlsafe_b64encode(hashlib.sha256(settings.auth_secret.encode()).digest()).decode()
    try:
        return MultiFernet([Fernet(key.encode())] + [Fernet(previous.encode()) for previous in settings.outbox_previous_encryption_keys])
    except (ValueError, TypeError):
        raise DeliveryUnavailable("encryption_invalid") from None


def encrypt_text(value: str) -> str:
    return cipher().encrypt(value.encode()).decode()


def decrypt_text(value: str) -> str:
    try:
        return cipher().decrypt(value.encode()).decode()
    except (InvalidToken, UnicodeError):
        raise DeliveryFailure("payload_decryption_failed", retryable=False) from None


def delivery_ready() -> bool:
    if settings.email_provider == "console":
        return settings.environment in {"development", "test"} and settings.auth_debug_code
    if not settings.email_from or any(char in settings.email_from for char in "\r\n"):
        return False
    if settings.email_provider == "resend":
        return bool(settings.resend_api_key)
    if settings.email_provider == "smtp":
        tls = settings.smtp_tls or settings.smtp_starttls
        return bool(settings.smtp_host) and (tls or settings.environment != "production") and (not settings.smtp_username or bool(settings.smtp_password))
    return False


def require_delivery():
    if not delivery_ready():
        raise DeliveryUnavailable("email_provider_unconfigured")
    cipher()


def google_ready() -> bool:
    return bool(settings.google_client_id and settings.google_client_secret and settings.google_redirect_uri)


def enqueue_email(db, recipient: str, subject: str, text: str, *, dedup_key: str, locale: str = "ru", expires_at=None) -> EmailOutbox:
    """Enqueue in the caller's transaction. Returns existing deduplicated item."""
    require_delivery()
    if not dedup_key or len(dedup_key) > 200 or len(subject) > 300 or any(char in subject for char in "\r\n") or len(text) > 100000:
        raise ValueError("Invalid email envelope")
    try:
        recipient = validate_email(recipient, check_deliverability=False, test_environment=settings.environment != "production").normalized
    except EmailNotValidError:
        raise ValueError("Invalid email recipient") from None
    existing = db.scalar(select(EmailOutbox).where(EmailOutbox.dedup_key == dedup_key))
    if existing:
        return existing
    payload = {"recipient": recipient, "subject": subject, "text": text, "locale": locale if locale in {"ru", "kk", "en"} else "ru"}
    row = EmailOutbox(dedup_key=dedup_key, encrypted_payload=encrypt_text(json.dumps(payload, ensure_ascii=False)), expires_at=expires_at)
    # A savepoint preserves the caller's transaction on a concurrent dedup race.
    try:
        with db.begin_nested():
            db.add(row)
            db.flush()
    except IntegrityError:
        row = db.scalar(select(EmailOutbox).where(EmailOutbox.dedup_key == dedup_key))
        if row is None:
            raise
    return row


def send_email(payload: dict, dedup_key: str) -> str:
    require_delivery()
    provider_key = hashlib.sha256(dedup_key.encode()).hexdigest()
    if settings.email_provider == "console":
        # Explicit local development only. Never selected implicitly.
        logging.getLogger("danaconnect.dev_mail").warning("DEVELOPMENT EMAIL to=%s subject=%s body=%s", payload["recipient"], payload["subject"], payload["text"])
        return "console-" + provider_key
    if settings.email_provider == "resend":
        try:
            response = httpx.post("https://api.resend.com/emails", headers={"Authorization": "Bearer " + settings.resend_api_key, "Idempotency-Key": "dc-" + provider_key}, json={"from": settings.email_from, "to": [payload["recipient"]], "subject": payload["subject"], "text": payload["text"]}, timeout=10)
        except httpx.HTTPError:
            raise DeliveryFailure("resend_network") from None
        if response.status_code not in {200, 201}:
            raise DeliveryFailure("resend_http_" + str(response.status_code), retryable=response.status_code in {408, 429} or response.status_code >= 500)
        try:
            identifier = response.json()["id"]
            if not isinstance(identifier, str) or not identifier or len(identifier) > 200:
                raise ValueError()
        except (ValueError, KeyError, TypeError):
            raise DeliveryFailure("resend_invalid_response") from None
        return identifier
    message = EmailMessage()
    message["From"] = settings.email_from
    message["To"] = payload["recipient"]
    message["Subject"] = payload["subject"]
    message["Message-ID"] = f"<dc-{provider_key}@danaconnect.invalid>"
    message.set_content(payload["text"])
    try:
        if settings.smtp_tls:
            connection = smtplib.SMTP_SSL(settings.smtp_host, settings.smtp_port, timeout=10, context=ssl.create_default_context())
        else:
            connection = smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=10)
        with connection:
            if settings.smtp_starttls:
                connection.starttls(context=ssl.create_default_context())
            if settings.smtp_username:
                connection.login(settings.smtp_username, settings.smtp_password)
            refused = connection.send_message(message)
            if refused:
                raise DeliveryFailure("smtp_recipient_refused", retryable=_recipient_refusal_retryable(refused))
    except smtplib.SMTPRecipientsRefused as exc:
        raise DeliveryFailure("smtp_recipient_refused", retryable=_recipient_refusal_retryable(exc.recipients)) from None
    except smtplib.SMTPResponseException as exc:
        raise DeliveryFailure("smtp_response_" + str(exc.smtp_code), retryable=400 <= exc.smtp_code < 500) from None
    except (smtplib.SMTPException, OSError):
        raise DeliveryFailure("smtp_connection") from None
    return str(message["Message-ID"])


def process_outbox(session_factory=SessionLocal, *, limit: int = 20, sender=None, outbox_id: str | None = None) -> dict:
    """Claim with compare-and-set leases, send outside transactions, bounded retry."""
    require_delivery()
    sender = sender or send_email
    result = {"claimed": 0, "sent": 0, "retried": 0, "failed": 0}
    for _ in range(max(0, min(limit, 100))):
        now, lease = utcnow(), str(uuid4())
        claimable = or_(and_(EmailOutbox.status == "pending", EmailOutbox.next_attempt_at <= now), and_(EmailOutbox.status == "leased", EmailOutbox.lease_until <= now))
        if outbox_id is not None:
            # An interactive OTP request must never dispatch unrelated mail.
            claimable = and_(claimable, EmailOutbox.id == outbox_id)
        with session_factory() as db:
            db.execute(update(EmailOutbox).where(claimable, EmailOutbox.attempts >= settings.outbox_max_attempts).values(status="failed", encrypted_payload="", lease_token=None, lease_until=None, last_error_code="attempts_exhausted"))
            candidate = db.scalar(select(EmailOutbox).where(claimable, EmailOutbox.attempts < settings.outbox_max_attempts).order_by(EmailOutbox.next_attempt_at, EmailOutbox.id).limit(1))
            if candidate is None:
                db.commit()
                break
            identifier, payload_blob, key, expiry = candidate.id, candidate.encrypted_payload, candidate.dedup_key, candidate.expires_at
            claimed = db.execute(update(EmailOutbox).where(EmailOutbox.id == identifier, claimable).values(status="leased", attempts=EmailOutbox.attempts + 1, lease_token=lease, lease_until=now + timedelta(seconds=settings.outbox_lease_seconds)))
            db.commit()
            if claimed.rowcount != 1:
                continue
        result["claimed"] += 1
        message_id, error, retryable = None, None, False
        try:
            if expiry and expiry <= utcnow():
                raise DeliveryFailure("message_expired", retryable=False)
            payload = json.loads(decrypt_text(payload_blob))
            # Cancellation/revocation may commit after claim. Recheck the
            # current lease before beginning delivery, without holding a DB
            # transaction across the provider call. An in-flight SMTP message
            # still cannot be recalled or guaranteed exactly once.
            with session_factory() as db:
                current = db.scalar(select(EmailOutbox).where(
                    EmailOutbox.id == identifier, EmailOutbox.lease_token == lease,
                    EmailOutbox.status == "leased",
                    EmailOutbox.encrypted_payload == payload_blob))
                if current is None or not current.encrypted_payload:
                    continue
                if current.expires_at and current.expires_at <= utcnow():
                    raise DeliveryFailure("message_expired", retryable=False)
            message_id = sender(payload, key)
            if not isinstance(message_id, str) or not message_id:
                raise DeliveryFailure("provider_missing_receipt")
        except DeliveryFailure as exc:
            error, retryable = exc.code, exc.retryable
        except DeliveryUnavailable:
            error, retryable = "provider_unconfigured", True
        except Exception:
            # Never retain provider bodies, OTPs, recipient addresses or traces.
            error, retryable = "delivery_unexpected", True
        with session_factory() as db:
            row = db.scalar(select(EmailOutbox).where(EmailOutbox.id == identifier, EmailOutbox.lease_token == lease, EmailOutbox.status == "leased"))
            if row is None:
                continue
            values = {"lease_token": None, "lease_until": None}
            if not error:
                values.update(status="sent", sent_at=utcnow(), provider_message_id=message_id[:200], encrypted_payload="", last_error_code=None)
                counter = "sent"
            elif retryable and row.attempts < settings.outbox_max_attempts and (row.expires_at is None or row.expires_at > utcnow()):
                values.update(status="pending", last_error_code=error, next_attempt_at=utcnow() + timedelta(seconds=min(3600, 30 * 2 ** (row.attempts - 1))))
                counter = "retried"
            else:
                values.update(status="failed", last_error_code=error, encrypted_payload="")
                counter = "failed"
            finished = db.execute(update(EmailOutbox).where(EmailOutbox.id == identifier, EmailOutbox.lease_token == lease, EmailOutbox.status == "leased").values(**values))
            db.commit()
            if finished.rowcount == 1:
                result[counter] += 1
    return result


def dispatch_email_now(db, outbox_id: str) -> str:
    """Attempt one committed OTP immediately, with the worker's leases/retries.

    Await the bounded provider call before responding: no detached serverless
    thread can lose a message after the HTTP response. A transient failure or
    active worker lease remains queued for the existing recovery schedule.
    """
    if db.in_transaction():
        raise ValueError("Immediate delivery requires a committed transaction")
    started = perf_counter()
    outcome = "queued"
    factory = sessionmaker(bind=db.get_bind(), expire_on_commit=False)
    try:
        process_outbox(factory, limit=1, outbox_id=outbox_id)
        with factory() as check:
            status = check.scalar(select(EmailOutbox.status).where(EmailOutbox.id == outbox_id))
        if status in {"sent", "failed"}:
            outcome = status
    except Exception:
        # Keep the durable message for recovery; never log secrets or bodies.
        logging.getLogger("danaconnect.mail").warning("otp_immediate_attempt_unavailable")
    logging.getLogger("danaconnect.mail").info(
        "otp_delivery outcome=%s elapsed_ms=%d", outcome, int((perf_counter() - started) * 1000))
    return outcome


def otp_email(code: str, locale: str) -> tuple[str, str]:
    templates = {
        "ru": ("Ваш код входа в DanaConnect", f"Код входа: {code}. Он действует {settings.otp_minutes} минут. Никому не сообщайте код. Если вы не запрашивали вход, игнорируйте письмо."),
        "kk": ("DanaConnect кіру коды", f"Кіру коды: {code}. Ол {settings.otp_minutes} минут жарамды. Кодты ешкімге бермеңіз. Кіруді сұрамаған болсаңыз, хатты елемеңіз."),
        "en": ("Your DanaConnect sign-in code", f"Sign-in code: {code}. It expires in {settings.otp_minutes} minutes. Do not share this code. If you did not request it, ignore this email."),
    }
    return templates.get(locale, templates["ru"])


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Process one bounded email outbox batch")
    parser.add_argument("--limit", type=int, default=20)
    print(process_outbox(limit=parser.parse_args().limit))
