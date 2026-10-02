"""Read-only operator indicators with a bounded, non-sensitive response shape.

All ages use the request's single UTC clock. Aggregates are informational reads,
not a transactional delivery audit or proof of receipt by a recipient.
"""
from datetime import datetime, timedelta
from typing import Literal, TypedDict

from sqlalchemy import and_, case, func, or_, select
from sqlalchemy.orm import Session

from app.models_delivery import EmailOutbox
from app.models_operations import WorkerHeartbeat


FailureCode = Literal[
    "attempts_exhausted", "message_expired", "payload_decryption_failed",
    "provider_missing_receipt", "provider_unconfigured", "delivery_unexpected",
    "resend_network", "resend_invalid_response", "smtp_recipient_refused",
    "smtp_connection", "booking_cancelled", "invitation_revoked", "resend_http",
    "smtp_response", "other",
]
KNOWN_FAILURE_CODES = (
    "attempts_exhausted", "message_expired", "payload_decryption_failed",
    "provider_missing_receipt", "provider_unconfigured", "delivery_unexpected",
    "resend_network", "resend_invalid_response", "smtp_recipient_refused",
    "smtp_connection", "booking_cancelled", "invitation_revoked",
)
# Delivery creates numeric provider codes. Expose only these fixed family names;
# never return an arbitrary database string or provider response text.
RESEND_HTTP_CODES = tuple(f"resend_http_{code}" for code in range(100, 600))
SMTP_RESPONSE_CODES = tuple(f"smtp_response_{code}" for code in range(100, 600))


class FailureCount(TypedDict):
    code: FailureCode
    count: int


class DeliverySnapshot(TypedDict):
    status_counts: dict[str, int]
    due_pending: int
    expired_pending: int
    expired_leases: int
    oldest_pending_at: datetime | None
    oldest_due_at: datetime | None
    oldest_due_age_seconds: int | None
    failures_last_24h: int
    failure_codes: list[FailureCount]


class RuleCounters(TypedDict, total=False):
    processed: int
    created: int
    skipped: int
    errors: int


class ReminderCounters(TypedDict, total=False):
    processed: int
    email_queued: int
    in_app_only: int
    errors: int


class EmailCounters(TypedDict, total=False):
    claimed: int
    sent: int
    retried: int
    failed: int


class EmailUnavailable(TypedDict):
    status: Literal["unconfigured"]


class WorkerSummary(TypedDict, total=False):
    rules: RuleCounters
    reminders: ReminderCounters
    email: EmailCounters | EmailUnavailable


class WorkerSnapshot(TypedDict):
    status: Literal["idle", "running", "success", "failed"]
    last_finished_at: datetime | None
    recent_success: bool
    last_started_at: datetime | None
    age_seconds: int | None
    duration_seconds: int | None
    running_age_seconds: int | None
    summary: WorkerSummary


class OperationsSignal(TypedDict):
    code: Literal[
        "email_unconfigured", "email_due_delayed", "email_expired_pending",
        "email_failed", "email_lease_expired", "worker_missing", "worker_failed",
        "worker_stale", "worker_running_long",
    ]
    severity: Literal["warning", "critical"]


def age_seconds(now: datetime, timestamp: datetime | None) -> int | None:
    return max(0, int((now - timestamp).total_seconds())) if timestamp else None


def delivery_snapshot(db: Session, now: datetime) -> DeliverySnapshot:
    pending = EmailOutbox.status == "pending"
    due = and_(pending, EmailOutbox.next_attempt_at <= now,
        or_(EmailOutbox.expires_at.is_(None), EmailOutbox.expires_at > now))
    expired_pending = and_(pending, EmailOutbox.expires_at <= now)
    expired_leases = and_(EmailOutbox.status == "leased",
        or_(EmailOutbox.lease_until.is_(None), EmailOutbox.lease_until <= now))
    recent_failed = and_(EmailOutbox.status == "failed",
        EmailOutbox.created_at >= now - timedelta(hours=24), EmailOutbox.created_at <= now)
    # Conditional counts and minima avoid reading envelopes or individual IDs.
    aggregate = db.execute(select(
        *(func.count(EmailOutbox.id).filter(EmailOutbox.status == status).label(status)
            for status in ("pending", "leased", "sent", "failed")),
        func.count(EmailOutbox.id).filter(due).label("due_pending"),
        func.count(EmailOutbox.id).filter(expired_pending).label("expired_pending"),
        func.count(EmailOutbox.id).filter(expired_leases).label("expired_leases"),
        func.min(EmailOutbox.created_at).filter(pending).label("oldest_pending_at"),
        func.min(EmailOutbox.next_attempt_at).filter(due).label("oldest_due_at"),
        func.count(EmailOutbox.id).filter(recent_failed).label("failures_last_24h"),
    )).one()._mapping
    safe_code = case(
        (EmailOutbox.last_error_code.in_(KNOWN_FAILURE_CODES), EmailOutbox.last_error_code),
        (EmailOutbox.last_error_code.in_(RESEND_HTTP_CODES), "resend_http"),
        (EmailOutbox.last_error_code.in_(SMTP_RESPONSE_CODES), "smtp_response"),
        else_="other",
    )
    failure_rows = db.execute(select(safe_code.label("code"), func.count(EmailOutbox.id))
        .where(EmailOutbox.status == "failed").group_by(safe_code).order_by(safe_code)).all()
    return {
        "status_counts": {status: int(aggregate[status]) for status in ("pending", "leased", "sent", "failed")},
        "due_pending": int(aggregate["due_pending"]),
        "expired_pending": int(aggregate["expired_pending"]),
        "expired_leases": int(aggregate["expired_leases"]),
        "oldest_pending_at": aggregate["oldest_pending_at"],
        "oldest_due_at": aggregate["oldest_due_at"],
        "oldest_due_age_seconds": age_seconds(now, aggregate["oldest_due_at"]),
        # No failed_at exists: this is current failure status within a creation
        # cohort, including intentional cancellation/revocation records.
        "failures_last_24h": int(aggregate["failures_last_24h"]),
        "failure_codes": [{"code": code, "count": int(count)} for code, count in failure_rows],
    }


def sanitized_summary(value: object) -> WorkerSummary:
    """Return only run_once's fixed counters; never recurse through stored JSON."""
    summary: WorkerSummary = {}
    if not isinstance(value, dict):
        return summary
    for group, fields in (
        ("rules", ("processed", "created", "skipped", "errors")),
        ("reminders", ("processed", "email_queued", "in_app_only", "errors")),
        ("email", ("claimed", "sent", "retried", "failed")),
    ):
        source = value.get(group)
        if not isinstance(source, dict):
            continue
        if group == "email" and source.get("status") == "unconfigured":
            summary["email"] = {"status": "unconfigured"}
            continue
        # bool is an int subclass, but cannot be a work counter.
        counters = {key: source[key] for key in fields
            if type(source.get(key)) is int and 0 <= source[key] <= 2**63 - 1}
        if counters:
            summary[group] = counters
    return summary


def worker_snapshot(heartbeat: WorkerHeartbeat | None, now: datetime) -> WorkerSnapshot:
    status = heartbeat.status if heartbeat and heartbeat.status in {"idle", "running", "success", "failed"} else "idle"
    started = heartbeat.started_at if heartbeat else None
    finished = heartbeat.finished_at if heartbeat else None
    duration = None
    if status in {"success", "failed"} and started and finished and finished >= started:
        duration = int((finished - started).total_seconds())
    return {
        "status": status,
        "last_finished_at": finished,
        "recent_success": bool(status == "success" and finished and finished > now - timedelta(minutes=5)),
        "last_started_at": started,
        "age_seconds": age_seconds(now, finished),
        "duration_seconds": duration,
        "running_age_seconds": age_seconds(now, started) if status == "running" else None,
        # run_once retains the previous completed summary while the next run is
        # in progress; this is not a live counter for a running batch.
        "summary": sanitized_summary(heartbeat.summary if heartbeat else None),
    }


def operations_signals(delivery: DeliverySnapshot, worker: WorkerSnapshot, *,
    email_configured: bool, heartbeat_present: bool) -> list[OperationsSignal]:
    signals: list[OperationsSignal] = []
    if not email_configured:
        signals.append({"code": "email_unconfigured", "severity": "warning"})
    due_age = delivery["oldest_due_age_seconds"]
    if due_age is not None and due_age >= 900:
        signals.append({"code": "email_due_delayed", "severity": "warning"})
    if delivery["expired_pending"]:
        signals.append({"code": "email_expired_pending", "severity": "warning"})
    # Normal cancellation/revocation deliberately fails an unsent envelope.
    # Keep these in all counts, but do not turn normal lifecycle actions into a
    # persistent operator failure alert.
    if any(item["count"] > 0 and item["code"] not in {"booking_cancelled", "invitation_revoked"}
        for item in delivery["failure_codes"]):
        signals.append({"code": "email_failed", "severity": "warning"})
    if delivery["expired_leases"]:
        signals.append({"code": "email_lease_expired", "severity": "warning"})
    if not heartbeat_present:
        signals.append({"code": "worker_missing", "severity": "warning"})
    elif worker["status"] == "running":
        running_age = worker["running_age_seconds"]
        if running_age is None:
            signals.append({"code": "worker_stale", "severity": "warning"})
        elif running_age >= 300:
            signals.append({"code": "worker_running_long", "severity": "warning"})
    else:
        if worker["status"] == "failed":
            signals.append({"code": "worker_failed", "severity": "critical"})
        if worker["age_seconds"] is None or worker["age_seconds"] >= 300:
            signals.append({"code": "worker_stale", "severity": "warning"})
    return signals
