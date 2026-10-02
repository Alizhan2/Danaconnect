"""Concrete scheduling with serialized per-user writes and atomic reservations.

PostgreSQL locks involved user rows in ID order. SQLite's first no-op user UPDATE
obtains its writer lock before interval/permission reads; the authentication read
transaction is closed first so it cannot cause a stale snapshot upgrade. The
scheduled-booking partial unique index adds a final database-level safeguard.
"""
from datetime import date, datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import or_, select, update
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session

from app.auth import has_current_consents, require_active
from app.database import get_db
from app.models import AuditEvent, Booking, Notification, Participation, Slot, User, utcnow
from app.schemas.bookings import BookingCreate, SlotCreate
from app.schemas.calendar_rules import MeetingURLInput, NoShowInput
from app.models_calendar import AvailabilityRule, BookingReminder, GeneratedRuleSlot
from app.models_delivery import EmailOutbox
from app.booking_lifecycle import cancel_reservation

router = APIRouter(tags=["calendar"])


def _active(db: Session, user: User, role: str | None = None):
    if role and user.role != role:
        raise HTTPException(403, "Недоступно для вашей роли")
    if user.account_status != "active" or (user.role != "admin" and not user.profile_completed):
        raise HTTPException(403, "Участник не допущен к работе на платформе")
    if not has_current_consents(db, user):
        raise HTTPException(403, "Необходимо принять актуальные обязательные документы")


def _lock_users(db: Session, user_ids: list[str]) -> dict[str, User]:
    """Start a fresh mutation transaction, then serialize all involved people."""
    ids = sorted(set(user_ids))
    db.rollback()
    if db.bind.dialect.name == "sqlite":
        try:
            for user_id in ids:
                db.execute(update(User).where(User.id == user_id).values(capacity=User.capacity))
        except OperationalError:
            db.rollback()
            raise HTTPException(409, "Расписание обновляется. Повторите действие")
    rows = db.scalars(select(User).where(User.id.in_(ids)).order_by(User.id).with_for_update()
                      .execution_options(populate_existing=True)).all()
    users = {item.id: item for item in rows}
    if len(users) != len(ids):
        raise HTTPException(404, "Участник не найден")
    return users


def _commit(db: Session):
    try:
        db.commit()
    except (IntegrityError, OperationalError):
        db.rollback()
        raise HTTPException(409, "Расписание изменилось. Обновите страницу и повторите действие")


def _flush(db: Session):
    try:
        db.flush()
    except (IntegrityError, OperationalError):
        db.rollback()
        raise HTTPException(409, "Расписание изменилось. Обновите страницу и повторите действие")


def _audit(db: Session, actor_id: str, action: str, entity_type: str, entity_id: str, **detail):
    db.add(AuditEvent(actor_id=actor_id, action=action, entity_type=entity_type,
                      entity_id=entity_id, detail=detail))


def _notify(db: Session, users: list[str], kind: str, title: str, body: str):
    for user_id in set(users):
        db.add(Notification(user_id=user_id, kind=kind, title=title, body=body))


def _slot_view(slot: Slot, mentor: User):
    return {"id": slot.id, "mentor_id": slot.mentor_id, "mentor_name": mentor.full_name,
            "starts_at": slot.starts_at, "ends_at": slot.ends_at, "timezone": slot.timezone,
            "mentor_timezone": mentor.timezone, "status": slot.status, "created_at": slot.created_at}


def _booking_view(db: Session, booking: Booking):
    slot = db.get(Slot, booking.slot_id)
    mentor, mentee = db.get(User, booking.mentor_id), db.get(User, booking.mentee_id)
    return {"id": booking.id, "slot_id": booking.slot_id, "mentee_id": booking.mentee_id,
            "mentor_id": booking.mentor_id, "participation_id": booking.participation_id,
            "status": booking.status, "meeting_url": booking.meeting_url,
            "created_at": booking.created_at, "mentor_name": mentor.full_name,
            "mentee_name": mentee.full_name, "starts_at": slot.starts_at,
            "ends_at": slot.ends_at, "timezone": slot.timezone, "mentor_timezone": mentor.timezone}


def _parse_from_date(value: str | None) -> datetime:
    if value is None:
        return utcnow()
    try:
        if len(value) == 10:
            return datetime.combine(date.fromisoformat(value), datetime.min.time(), tzinfo=timezone.utc)
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError()
        return parsed.astimezone(timezone.utc)
    except ValueError:
        raise HTTPException(422, "from_date: укажите ISO дату или дату-время с часовым поясом")


@router.get("/slots")
def list_slots(mentor_id: str | None = None, from_date: str | None = None,
               limit: int = Query(100, ge=1, le=200), offset: int = Query(0, ge=0),
               user: User = Depends(require_active), db: Session = Depends(get_db)):
    own = mentor_id == user.id and user.role == "mentor"
    query = select(Slot, User).join(User, User.id == Slot.mentor_id).where(
        Slot.starts_at >= _parse_from_date(from_date), Slot.status != "cancelled",
        User.account_status == "active", User.role == "mentor", User.profile_completed.is_(True))
    if mentor_id:
        query = query.where(Slot.mentor_id == mentor_id)
    if not own and user.role != "admin":
        query = query.where(Slot.status == "available")
    rows = db.execute(query.order_by(Slot.starts_at, Slot.id).offset(offset).limit(limit)).all()
    return [_slot_view(slot, mentor) for slot, mentor in rows if has_current_consents(db, mentor)]


@router.post("/slots", status_code=201)
def create_slot(payload: SlotCreate, user: User = Depends(require_active), db: Session = Depends(get_db)):
    actor_id = user.id
    people = _lock_users(db, [actor_id])
    mentor = people[actor_id]
    _active(db, mentor, "mentor")
    if payload.starts_at <= utcnow():
        raise HTTPException(422, "Слот должен начинаться в будущем")
    overlap = db.scalar(select(Slot.id).where(Slot.mentor_id == actor_id,
                        Slot.status != "cancelled", Slot.starts_at < payload.ends_at,
                        Slot.ends_at > payload.starts_at).limit(1))
    if overlap:
        raise HTTPException(409, "Этот интервал пересекается с существующим слотом")
    slot = Slot(mentor_id=actor_id, starts_at=payload.starts_at, ends_at=payload.ends_at,
                timezone=payload.timezone, status="available")
    db.add(slot)
    _flush(db)
    _audit(db, actor_id, "slot.created", "slot", slot.id,
           starts_at=slot.starts_at.isoformat(), ends_at=slot.ends_at.isoformat(), timezone=slot.timezone)
    _commit(db)
    return _slot_view(slot, mentor)


@router.delete("/slots/{slot_id}")
def delete_slot(slot_id: str, user: User = Depends(require_active), db: Session = Depends(get_db)):
    actor_id = user.id
    _active(db, _lock_users(db, [actor_id])[actor_id], "mentor")
    slot = db.get(Slot, slot_id, populate_existing=True)
    if not slot or slot.mentor_id != actor_id:
        raise HTTPException(404, "Слот не найден")
    if slot.status == "cancelled":
        return {"id": slot.id, "status": slot.status}
    if slot.starts_at <= utcnow() or slot.status != "available":
        raise HTTPException(409, "Можно удалить только будущий свободный слот")
    if db.scalar(select(Booking.id).where(Booking.slot_id == slot.id, Booking.status == "scheduled").limit(1)):
        raise HTTPException(409, "Сначала отмените встречу")
    slot.status = "cancelled"
    _audit(db, actor_id, "slot.cancelled", "slot", slot.id)
    _commit(db)
    return {"id": slot.id, "status": slot.status}


@router.get("/bookings")
def list_bookings(limit: int = Query(100, ge=1, le=200), offset: int = Query(0, ge=0),
                  user: User = Depends(require_active), db: Session = Depends(get_db)):
    query = select(Booking).join(Slot, Slot.id == Booking.slot_id)
    if user.role != "admin":
        query = query.where(or_(Booking.mentee_id == user.id, Booking.mentor_id == user.id))
    rows = db.scalars(query.order_by(Slot.starts_at.desc(), Booking.id).offset(offset).limit(limit)).all()
    return [_booking_view(db, row) for row in rows]


def _participation(db: Session, mentee_id: str, mentor_id: str, participation_id: str | None):
    if participation_id:
        row = db.get(Participation, participation_id, populate_existing=True)
        if not row or row.mentee_id != mentee_id or row.mentor_id != mentor_id:
            raise HTTPException(404, "Участие с этими сторонами не найдено")
        if row.status != "active":
            raise HTTPException(409, "Новые встречи разрешены только при активном участии")
        return row
    rows = db.scalars(select(Participation).where(Participation.mentee_id == mentee_id,
                      Participation.mentor_id == mentor_id, Participation.status.in_(["active", "paused"]))
                      .order_by(Participation.started_at.desc(), Participation.id)).all()
    active = next((row for row in rows if row.status == "active"), None)
    if active:
        return active
    if rows:
        raise HTTPException(409, "Участие на паузе. Возобновите его перед записью")
    return None


@router.post("/bookings", status_code=201)
def create_booking(payload: BookingCreate, user: User = Depends(require_active), db: Session = Depends(get_db)):
    actor_id = user.id
    slot = db.get(Slot, payload.slot_id)
    if not slot:
        raise HTTPException(404, "Слот не найден")
    mentor_id = slot.mentor_id
    people = _lock_users(db, [actor_id, mentor_id])
    mentee, mentor = people[actor_id], people[mentor_id]
    _active(db, mentee, "mentee")
    _active(db, mentor, "mentor")
    slot = db.get(Slot, payload.slot_id, populate_existing=True)
    if slot.starts_at <= utcnow():
        raise HTTPException(409, "На прошедший слот записаться нельзя")
    participation = _participation(db, actor_id, mentor_id, payload.participation_id)
    if not participation and not mentor.intake_open:
        raise HTTPException(409, "Ментор закрыл приём новых участников")
    # A repeat by the same mentee returns the already-created reservation.
    existing = db.scalar(select(Booking).where(Booking.slot_id == slot.id, Booking.status == "scheduled"))
    if existing:
        if existing.mentee_id == actor_id and existing.participation_id == (participation.id if participation else None):
            return _booking_view(db, existing)
        raise HTTPException(409, "Слот уже занят")
    busy = db.scalar(select(Booking.id).join(Slot, Slot.id == Booking.slot_id).where(
        Booking.status == "scheduled", Slot.starts_at < slot.ends_at, Slot.ends_at > slot.starts_at,
        or_(Booking.mentee_id.in_([actor_id, mentor_id]), Booking.mentor_id.in_([actor_id, mentor_id])))
        .limit(1))
    if busy:
        raise HTTPException(409, "В это время у одного из участников уже есть встреча")
    changed = db.execute(update(Slot).where(Slot.id == slot.id, Slot.status == "available")
                         .values(status="booked").execution_options(synchronize_session="fetch"))
    if changed.rowcount != 1:
        raise HTTPException(409, "Слот уже занят или отменён")
    booking = Booking(slot_id=slot.id, mentee_id=actor_id, mentor_id=mentor_id,
                      participation_id=participation.id if participation else None, status="scheduled")
    db.add(booking)
    _flush(db)
    _audit(db, actor_id, "booking.created", "booking", booking.id, slot_id=slot.id)
    _notify(db, [actor_id, mentor_id], "booking_scheduled", "Встреча запланирована",
            f"{slot.starts_at.isoformat()} UTC. Часовой пояс расписания: {slot.timezone}.")
    _commit(db)
    return _booking_view(db, booking)


def _locked_booking(db: Session, booking_id: str, actor_id: str):
    booking = db.get(Booking, booking_id)
    if not booking:
        raise HTTPException(404, "Встреча не найдена")
    ids = [actor_id, booking.mentee_id, booking.mentor_id]
    users = _lock_users(db, ids)
    actor = users[actor_id]
    _active(db, actor)
    booking = db.get(Booking, booking_id, populate_existing=True)
    if actor.role != "admin" and actor_id not in [booking.mentee_id, booking.mentor_id]:
        raise HTTPException(404, "Встреча не найдена")
    return booking, db.get(Slot, booking.slot_id, populate_existing=True), actor


@router.post("/bookings/{booking_id}/cancel")
def cancel_booking(booking_id: str, user: User = Depends(require_active), db: Session = Depends(get_db)):
    actor_id = user.id
    booking, slot, actor = _locked_booking(db, booking_id, actor_id)
    if booking.status == "cancelled":
        return _booking_view(db, booking)
    if booking.status != "scheduled" or slot.starts_at <= utcnow():
        raise HTTPException(409, "Можно отменить только будущую запланированную встречу")
    cancel_reservation(db, booking)
    _audit(db, actor_id, "booking.cancelled", "booking", booking.id, slot_id=slot.id)
    _notify(db, [booking.mentee_id, booking.mentor_id], "booking_cancelled", "Встреча отменена",
            f"Отменена встреча {slot.starts_at.isoformat()}. Проверьте доступное время в расписании.")
    _commit(db)
    return _booking_view(db, booking)


@router.patch("/bookings/{booking_id}/meeting-url")
def update_meeting_url(booking_id: str, payload: MeetingURLInput, user: User = Depends(require_active), db: Session = Depends(get_db)):
    booking, slot, actor = _locked_booking(db, booking_id, user.id)
    if actor.role != "mentor" or booking.mentor_id != actor.id:
        raise HTTPException(403, "Ссылку на встречу задаёт её ментор")
    if booking.status != "scheduled":
        raise HTTPException(409, "Ссылку можно изменить только для запланированной встречи")
    booking.meeting_url = str(payload.meeting_url) if payload.meeting_url else None
    _audit(db, actor.id, "booking.meeting_url_updated", "booking", booking.id)
    _notify(db, [booking.mentee_id], "booking_link", "Ссылка на встречу обновлена", "Проверьте ссылку в карточке вашей встречи.")
    _commit(db)
    return _booking_view(db, booking)


@router.post("/bookings/{booking_id}/no-show")
def mark_no_show(booking_id: str, payload: NoShowInput, user: User = Depends(require_active), db: Session = Depends(get_db)):
    booking, slot, actor = _locked_booking(db, booking_id, user.id)
    if actor.role != "mentor" or booking.mentor_id != actor.id:
        raise HTTPException(403, "Неявку может отметить только ментор встречи")
    if booking.status == "no_show":
        return _booking_view(db, booking)
    if booking.status != "scheduled" or slot.starts_at > utcnow():
        raise HTTPException(409, "Неявку можно отметить после начала запланированной встречи")
    booking.status = "no_show"
    _audit(db, actor.id, "booking.no_show", "booking", booking.id, reason=payload.reason)
    _notify(db, [booking.mentee_id], "booking_no_show", "Ментор отметил неявку", payload.reason)
    _commit(db)
    return _booking_view(db, booking)


@router.post("/bookings/{booking_id}/complete")
def complete_booking(booking_id: str, user: User = Depends(require_active), db: Session = Depends(get_db)):
    actor_id = user.id
    booking, slot, actor = _locked_booking(db, booking_id, actor_id)
    if actor.role != "mentor" or booking.mentor_id != actor_id:
        raise HTTPException(403, "Подтвердить встречу может только её ментор")
    if booking.status == "completed":
        return _booking_view(db, booking)
    if booking.status != "scheduled" or slot.starts_at > utcnow():
        raise HTTPException(409, "Подтвердите встречу после начала запланированного времени")
    booking.status = "completed"
    from app.services.growth import sync_user_progress
    sync_user_progress(db, booking.mentee_id)
    sync_user_progress(db, booking.mentor_id)
    _audit(db, actor_id, "booking.completed", "booking", booking.id)
    _notify(db, [booking.mentee_id], "booking_completed", "Встреча подтверждена",
            "Ментор подтвердил проведённую встречу. Она будет учтена в результате участия.")
    _commit(db)
    return _booking_view(db, booking)
