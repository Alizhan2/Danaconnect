"""Explicit calendar worker: persisted weekly rules, reminders and mail dispatch.

Run `python -m app.jobs_calendar --once` for a bounded batch or omit --once to
run periodically under the deployment supervisor. No scheduling occurs on API
startup. The clock is UTC; rule interpretation uses its IANA timezone.
"""
import argparse
import logging
import time as time_module
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import and_, case, func, or_, select
from sqlalchemy.exc import IntegrityError

from app.auth import has_current_consents
from app.config import settings
from app.profile_state import admitted_profile
from app.database import SessionLocal
from app.delivery import DeliveryUnavailable, enqueue_email, process_outbox
from app.models import Booking, Notification, Slot, User, utcnow
from app.models_calendar import AvailabilityRule, BookingReminder, GeneratedRuleSlot
from app.models_operations import WorkerHeartbeat
from app.jobs_admin_invites import cleanup_invitations
from app.routers.bookings import _lock_users


def wall_to_utc(value: datetime, zone: ZoneInfo, fold_policy: str) -> datetime | None:
    """Reject nonexistent local times; choose an explicit ambiguous occurrence."""
    possibilities = []
    for fold in (0, 1):
        instant = value.replace(tzinfo=zone, fold=fold).astimezone(timezone.utc)
        if instant.astimezone(zone).replace(tzinfo=None) == value and instant not in possibilities:
            possibilities.append(instant)
    if not possibilities:
        return None
    possibilities.sort()
    return possibilities[-1] if fold_policy == "second" else possibilities[0]


def generate_rule(db, rule: AvailabilityRule, *, now=None):
    """Caller holds the mentor lock. Never modifies an existing booked slot."""
    now = now or utcnow()
    zone = ZoneInfo(rule.timezone)
    today = now.astimezone(zone).date()
    until = today + timedelta(weeks=rule.horizon_weeks)
    if rule.ends_on:
        until = min(until, rule.ends_on + timedelta(days=1))
    stats = {"created": 0, "existing": 0, "conflicts": 0, "dst_skipped": 0, "generated_until": until.isoformat()}
    if not rule.active:
        return stats
    day = max(today, rule.starts_on)
    existing_keys = set(db.scalars(select(GeneratedRuleSlot.occurrence_key).join(Slot, Slot.id == GeneratedRuleSlot.slot_id).where(GeneratedRuleSlot.rule_id == rule.id, GeneratedRuleSlot.revision == rule.revision, Slot.ends_at > now)).all())
    intervals = db.scalars(select(Slot).where(Slot.mentor_id == rule.mentor_id, Slot.status != "cancelled", Slot.ends_at > now)).all()
    while day < until:
        if day.weekday() == rule.weekday:
            wall, end_wall = datetime.combine(day, rule.start_time), datetime.combine(day, rule.end_time)
            while wall + timedelta(minutes=rule.slot_minutes) <= end_wall:
                wall_end = wall + timedelta(minutes=rule.slot_minutes)
                key = f"{rule.revision}:{wall.isoformat(timespec='minutes')}:{rule.dst_fold}"
                start, end = wall_to_utc(wall, zone, rule.dst_fold), wall_to_utc(wall_end, zone, rule.dst_fold)
                wall = wall_end
                if start is None or end is None or end - start != timedelta(minutes=rule.slot_minutes):
                    stats["dst_skipped"] += 1
                    continue
                if start <= now:
                    continue
                if key in existing_keys:
                    stats["existing"] += 1
                    continue
                if any(slot.starts_at < end and slot.ends_at > start for slot in intervals):
                    stats["conflicts"] += 1
                    continue
                slot = Slot(mentor_id=rule.mentor_id, starts_at=start, ends_at=end, timezone=rule.timezone, status="available")
                db.add(slot)
                db.flush()
                db.add(GeneratedRuleSlot(rule_id=rule.id, slot_id=slot.id, occurrence_key=key, revision=rule.revision))
                intervals.append(slot)
                existing_keys.add(key)
                stats["created"] += 1
        day += timedelta(days=1)
    rule.generated_until, rule.updated_at = until, now
    return stats


def regenerate_rules(session_factory=SessionLocal, *, limit=100):
    stats = {"processed": 0, "created": 0, "skipped": 0, "errors": 0}
    with session_factory() as db:
        rule_ids = list(db.scalars(select(AvailabilityRule.id).where(AvailabilityRule.active.is_(True)).order_by(AvailabilityRule.updated_at, AvailabilityRule.id).limit(max(1, min(limit, 500)))).all())
    for identifier in rule_ids:
        with session_factory() as db:
            try:
                rule = db.get(AvailabilityRule, identifier)
                if not rule or not rule.active:
                    continue
                mentor_id = rule.mentor_id
                people = _lock_users(db, [mentor_id])
                mentor = people[mentor_id]
                if mentor.role != "mentor" or mentor.account_status != "active" or not admitted_profile(mentor) or not has_current_consents(db, mentor):
                    stats["skipped"] += 1
                    db.rollback()
                    continue
                rule = db.get(AvailabilityRule, identifier, populate_existing=True)
                # A disable/removal can commit while this worker waits for the
                # mentor lock. Eligibility must use the post-lock row state.
                if not rule or not rule.active:
                    db.rollback()
                    continue
                generated = generate_rule(db, rule)
                db.commit()
                stats["processed"] += 1
                stats["created"] += generated["created"]
            except Exception:
                db.rollback()
                stats["errors"] += 1
                logging.getLogger("danaconnect.calendar").error("Calendar rule generation failed for record %s", identifier)
    return stats


def reminder_content(user: User, other: User, slot: Slot, booking: Booking, kind: str):
    locale = getattr(user, "preferred_locale", "ru")
    local_start = slot.starts_at.astimezone(ZoneInfo(user.timezone))
    when = local_start.strftime("%Y-%m-%d %H:%M") + " · " + user.timezone
    titles = {"ru": "Напоминание о встрече DanaConnect", "kk": "DanaConnect кездесуі туралы еске салу", "en": "DanaConnect meeting reminder"}
    bodies = {
        "ru": f"Встреча с {other.full_name}: {when}. До встречи {'менее часа' if kind == '1h' else 'около суток'}.",
        "kk": f"{other.full_name} қатысушысымен кездесу: {when}. Кездесуге {'бір сағаттан аз' if kind == '1h' else 'шамамен бір тәулік'} қалды.",
        "en": f"Meeting with {other.full_name}: {when}. The meeting starts in {'less than one hour' if kind == '1h' else 'about 24 hours'}.",
    }
    body = bodies.get(locale, bodies["ru"])
    # Open the current private card; a queued email cannot retain a superseded
    # meeting link after the mentor changes it or cancels the meeting.
    body += "\n" + settings.frontend_url.rstrip("/") + "/calendar"
    return titles.get(locale, titles["ru"]), body, locale if locale in titles else "ru"


def enqueue_reminders(session_factory=SessionLocal, *, limit=200, now=None):
    now = now or utcnow()
    stats = {"processed": 0, "email_queued": 0, "in_app_only": 0, "errors": 0}
    with session_factory() as db:
        due_kind = case((Slot.starts_at <= now + timedelta(hours=1), "1h"), else_="24h")
        delivered = select(func.count(BookingReminder.id)).where(BookingReminder.booking_id == Booking.id, BookingReminder.kind == due_kind, BookingReminder.user_id.in_([Booking.mentee_id, Booking.mentor_id])).correlate(Booking, Slot).scalar_subquery()
        due_window = or_(Slot.starts_at <= now + timedelta(hours=1), and_(Slot.starts_at > now + timedelta(hours=23), Slot.starts_at <= now + timedelta(hours=24)))
        identifiers = list(db.scalars(select(Booking.id).join(Slot, Slot.id == Booking.slot_id).where(Booking.status == "scheduled", Slot.starts_at > now, due_window, delivered < 2).order_by(Slot.starts_at, Booking.id).limit(max(1, min(limit, 1000)))).all())
    for identifier in identifiers:
        with session_factory() as db:
            try:
                booking = db.get(Booking, identifier)
                if not booking:
                    continue
                people = _lock_users(db, [booking.mentor_id, booking.mentee_id])
                booking = db.get(Booking, identifier, populate_existing=True)
                slot = db.get(Slot, booking.slot_id)
                if booking.status != "scheduled" or slot.starts_at <= now:
                    db.rollback()
                    continue
                seconds = (slot.starts_at - now).total_seconds()
                kind = "1h" if 0 < seconds <= 3600 else "24h" if 23 * 3600 < seconds <= 24 * 3600 else None
                if kind is None or any(person.account_status != "active" or not has_current_consents(db, person) for person in people.values()):
                    db.rollback()
                    continue
                for user_id in (booking.mentee_id, booking.mentor_id):
                    existing = db.scalar(select(BookingReminder.id).where(BookingReminder.booking_id == booking.id, BookingReminder.user_id == user_id, BookingReminder.kind == kind))
                    if existing:
                        continue
                    person = people[user_id]
                    other = people[booking.mentor_id if user_id == booking.mentee_id else booking.mentee_id]
                    title, body, locale = reminder_content(person, other, slot, booking, kind)
                    notification = Notification(user_id=user_id, kind="booking_reminder", title=title, body=body)
                    db.add(notification)
                    db.flush()
                    dedup = f"booking-reminder:{booking.id}:{user_id}:{kind}"
                    row = BookingReminder(booking_id=booking.id, user_id=user_id, kind=kind, dedup_key=dedup, notification_id=notification.id, delivery_status="in_app_only")
                    try:
                        email = enqueue_email(db, person.email, title, body, dedup_key=dedup, locale=locale, expires_at=slot.starts_at)
                        row.email_outbox_id, row.delivery_status = email.id, "email_queued"
                    except DeliveryUnavailable:
                        pass
                    db.add(row)
                    stats[row.delivery_status] += 1
                db.commit()
                stats["processed"] += 1
            except Exception:
                db.rollback()
                stats["errors"] += 1
                logging.getLogger("danaconnect.calendar").error("Booking reminder enqueue failed for record %s", identifier)
    return stats


def run_once(session_factory=SessionLocal):
    with session_factory() as db:
        heartbeat = db.get(WorkerHeartbeat, "calendar")
        if heartbeat is None:
            heartbeat = WorkerHeartbeat(id="calendar")
            try:
                with db.begin_nested():
                    db.add(heartbeat)
                    db.flush()
            except IntegrityError:
                heartbeat = db.get(WorkerHeartbeat, "calendar", populate_existing=True)
        heartbeat.started_at, heartbeat.status = utcnow(), "running"
        db.commit()
    result = {"invitations": cleanup_invitations(session_factory),
              "rules": regenerate_rules(session_factory), "reminders": enqueue_reminders(session_factory)}
    try:
        result["email"] = process_outbox(session_factory)
    except DeliveryUnavailable:
        result["email"] = {"status": "unconfigured"}
    with session_factory() as db:
        heartbeat = db.get(WorkerHeartbeat, "calendar")
        heartbeat.finished_at, heartbeat.summary = utcnow(), result
        heartbeat.status = "failed" if any(value.get("errors", 0) for value in result.values()) else "success"
        db.commit()
    return result


def main():
    parser = argparse.ArgumentParser(description="Calendar recurrence, reminder and encrypted email worker")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--interval", type=int, default=60)
    args = parser.parse_args()
    if not 15 <= args.interval <= 3600:
        parser.error("--interval must be between 15 and 3600 seconds")
    while True:
        print(run_once(), flush=True)
        if args.once:
            break
        time_module.sleep(args.interval)


if __name__ == "__main__":
    main()
