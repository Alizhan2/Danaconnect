"""Cancellation shared by meetings, participation closure and account blocking."""
from sqlalchemy import select, update
from app.models import Slot
from app.models_calendar import AvailabilityRule, BookingReminder, GeneratedRuleSlot
from app.models_delivery import EmailOutbox


def cancel_reservation(db, booking, *, disable_slot=False):
    booking.status = "cancelled"
    slot = db.get(Slot, booking.slot_id, populate_existing=True)
    generated = db.scalar(select(GeneratedRuleSlot).where(GeneratedRuleSlot.slot_id == slot.id))
    rule = db.get(AvailabilityRule, generated.rule_id) if generated else None
    stale_rule = generated is not None and (rule is None or not rule.active or generated.revision != rule.revision)
    if slot.status == "booked":
        slot.status = "cancelled" if disable_slot or stale_rule else "available"
    ids = select(BookingReminder.email_outbox_id).where(BookingReminder.booking_id == booking.id,
        BookingReminder.email_outbox_id.is_not(None))
    db.execute(update(EmailOutbox).where(EmailOutbox.id.in_(ids),
        EmailOutbox.status.in_(["pending", "leased"])).values(status="failed", encrypted_payload="",
        lease_token=None, lease_until=None, last_error_code="booking_cancelled"))
    # An email already accepted by its provider cannot be recalled.
    return slot
