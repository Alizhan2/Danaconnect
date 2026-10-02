"""Private calendar snapshots. No public feeds or third-party calendar access."""
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.auth import require_active, requested_locale
from app.database import get_db
from app.models import Booking, Slot, User, utcnow

router = APIRouter(tags=["calendar"])


def ical_text(value: str) -> str:
    value = "".join(character for character in value if (ord(character) >= 32 and ord(character) != 127) or character in "\n\r\t")
    return value.replace("\\", "\\\\").replace("\r\n", "\n").replace("\r", "\n").replace("\n", "\\n").replace(";", "\\;").replace(",", "\\,")


def fold_line(value: str) -> str:
    # RFC 5545 measures UTF-8 octets; never split the bytes of a character.
    lines, current, length = [], "", 0
    for character in value:
        size = len(character.encode("utf-8"))
        if length + size > 75:
            lines.append(current)
            current, length = " ", 1
        current += character
        length += size
    lines.append(current)
    return "\r\n".join(lines)


def stamp(value: datetime) -> str:
    return value.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


@router.get("/me/calendar.ics")
def calendar_snapshot(request: Request, starts_after: datetime | None = None,
    ends_before: datetime | None = None, include_cancelled: bool = False,
    user: User = Depends(require_active), db: Session = Depends(get_db)):
    now = utcnow()
    start, end = starts_after or now - timedelta(days=30), ends_before or now + timedelta(days=180)
    if start.tzinfo is None or end.tzinfo is None or not start < end or end - start > timedelta(days=366):
        raise HTTPException(422, "Выберите период до одного года с указанием часового пояса")
    statement = select(Booking, Slot).join(Slot, Slot.id == Booking.slot_id).where(
        or_(Booking.mentee_id == user.id, Booking.mentor_id == user.id),
        Slot.starts_at >= start, Slot.starts_at < end)
    if not include_cancelled:
        statement = statement.where(Booking.status != "cancelled")
    rows = db.execute(statement.order_by(Slot.starts_at, Booking.id).limit(1001)).all()
    if len(rows) > 1000:
        raise HTTPException(422, "Сократите период: в календаре больше 1000 встреч")
    locale = requested_locale(request, user.preferred_locale)
    copy = {"ru": ("Календарь DanaConnect", "Встреча DanaConnect", "Участник", "Статус", "Снимок календаря. Изменения встреч не синхронизируются автоматически."),
        "kk": ("DanaConnect күнтізбесі", "DanaConnect кездесуі", "Қатысушы", "Күйі", "Күнтізбе көшірмесі. Кездесу өзгерістері автоматты түрде синхрондалмайды."),
        "en": ("DanaConnect calendar", "DanaConnect meeting", "Participant", "Status", "Calendar snapshot. Meeting changes do not sync automatically.")}[locale]
    states = {"ru": {"scheduled": "Запланирована", "completed": "Проведена", "cancelled": "Отменена", "no_show": "Не состоялась"},
        "kk": {"scheduled": "Жоспарланған", "completed": "Өткізілген", "cancelled": "Болдырылмаған", "no_show": "Өтпеді"},
        "en": {"scheduled": "Scheduled", "completed": "Completed", "cancelled": "Cancelled", "no_show": "Did not take place"}}[locale]
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//DanaConnect//Private calendar snapshot//EN", "CALSCALE:GREGORIAN", "X-WR-CALNAME:" + ical_text(copy[0])]
    for booking, slot in rows:
        other_id = booking.mentor_id if user.id == booking.mentee_id else booking.mentee_id
        other = db.get(User, other_id)
        description = f"{copy[2]}: {other.full_name if other else ''}\n{copy[3]}: {states.get(booking.status, booking.status)}\n{copy[4]}"
        lines.extend(["BEGIN:VEVENT", f"UID:{booking.id}@danaconnect", "DTSTAMP:" + stamp(now),
            "DTSTART:" + stamp(slot.starts_at), "DTEND:" + stamp(slot.ends_at),
            "SUMMARY:" + ical_text(copy[1]), "DESCRIPTION:" + ical_text(description),
            "CLASS:PRIVATE", "STATUS:" + ("CANCELLED" if booking.status == "cancelled" else "CONFIRMED"),
            "X-DANACONNECT-STATUS:" + booking.status])
        # Cancelled historical reservations cannot retain a stale meeting link.
        if booking.meeting_url and booking.status == "scheduled" and booking.meeting_url.startswith("https://"):
            lines.append("URL:" + quote(booking.meeting_url, safe="/:?#[]@!$&'()*+,;=%"))
        lines.append("END:VEVENT")
    lines.append("END:VCALENDAR")
    body = "\r\n".join(fold_line(line) for line in lines) + "\r\n"
    return Response(body.encode("utf-8"), media_type="text/calendar; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="danaconnect-calendar.ics"', "Cache-Control": "private, no-store"})
