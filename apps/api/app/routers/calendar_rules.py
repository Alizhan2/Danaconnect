"""Own weekly scheduling rules; concrete booked occurrences remain immutable."""
from datetime import timedelta
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth import require_active
from app.database import get_db
from app.jobs_calendar import generate_rule
from app.models import Booking, Slot, User, utcnow
from app.models_calendar import AvailabilityRule, GeneratedRuleSlot
from app.routers.bookings import _active, _audit, _commit, _flush, _lock_users
from app.schemas.calendar_rules import AvailabilityInput


router = APIRouter(tags=["weekly-calendar"])


def rule_view(rule):
    return {"id": rule.id, "mentor_id": rule.mentor_id, "weekday": rule.weekday, "start_time": rule.start_time.isoformat(timespec="minutes"), "end_time": rule.end_time.isoformat(timespec="minutes"), "timezone": rule.timezone, "slot_minutes": rule.slot_minutes, "starts_on": rule.starts_on, "ends_on": rule.ends_on, "horizon_weeks": rule.horizon_weeks, "dst_fold": rule.dst_fold, "revision": rule.revision, "active": rule.active, "generated_until": rule.generated_until, "created_at": rule.created_at, "updated_at": rule.updated_at}


def cancel_future_free(db, rule):
    rows = db.scalars(select(Slot).join(GeneratedRuleSlot, GeneratedRuleSlot.slot_id == Slot.id).where(GeneratedRuleSlot.rule_id == rule.id, Slot.starts_at > utcnow(), Slot.status == "available")).all()
    count = 0
    for slot in rows:
        booked = db.scalar(select(Booking.id).where(Booking.slot_id == slot.id, Booking.status == "scheduled").limit(1))
        if booked is None:
            slot.status = "cancelled"
            count += 1
    db.flush()
    return count


def validate_date_bounds(payload):
    today = utcnow().astimezone(ZoneInfo(payload.timezone)).date()
    if payload.starts_on > today + timedelta(days=366):
        raise HTTPException(422, "Начало расписания должно быть в пределах следующего года")
    if payload.ends_on and payload.ends_on < today:
        raise HTTPException(422, "Дата окончания расписания уже прошла")


@router.get("/availability-rules")
def list_rules(limit: int = Query(50, ge=1, le=100), offset: int = Query(0, ge=0), user: User = Depends(require_active), db: Session = Depends(get_db)):
    _active(db, user, "mentor")
    rows = db.scalars(select(AvailabilityRule).where(AvailabilityRule.mentor_id == user.id).order_by(AvailabilityRule.active.desc(), AvailabilityRule.weekday, AvailabilityRule.start_time).limit(limit).offset(offset)).all()
    return [rule_view(row) for row in rows]


@router.post("/availability-rules", status_code=201)
def create_rule(payload: AvailabilityInput, user: User = Depends(require_active), db: Session = Depends(get_db)):
    actor_id = user.id
    mentor = _lock_users(db, [actor_id])[actor_id]
    _active(db, mentor, "mentor")
    validate_date_bounds(payload)
    count = db.scalar(select(func.count(AvailabilityRule.id)).where(AvailabilityRule.mentor_id == actor_id, AvailabilityRule.active.is_(True)))
    if count >= 20:
        raise HTTPException(409, "Разрешено не более 20 активных правил расписания")
    rule = AvailabilityRule(mentor_id=actor_id, **payload.model_dump())
    db.add(rule)
    _flush(db)
    generation = generate_rule(db, rule)
    _audit(db, actor_id, "availability.created", "availability_rule", rule.id, timezone=rule.timezone, horizon_weeks=rule.horizon_weeks)
    _commit(db)
    return {"rule": rule_view(rule), "generation": generation}


@router.patch("/availability-rules/{rule_id}")
def edit_rule(rule_id: str, payload: AvailabilityInput, user: User = Depends(require_active), db: Session = Depends(get_db)):
    actor_id = user.id
    _active(db, _lock_users(db, [actor_id])[actor_id], "mentor")
    rule = db.get(AvailabilityRule, rule_id, populate_existing=True)
    if not rule or rule.mentor_id != actor_id:
        raise HTTPException(404, "Правило расписания не найдено")
    if not rule.active:
        raise HTTPException(409, "Создайте новое правило вместо отключённого")
    validate_date_bounds(payload)
    values = payload.model_dump()
    changed = any(getattr(rule, key) != value for key, value in values.items())
    cancelled = 0
    if changed:
        cancelled = cancel_future_free(db, rule)
        for key, value in values.items():
            setattr(rule, key, value)
        rule.revision += 1
    generation = generate_rule(db, rule)
    _audit(db, actor_id, "availability.updated", "availability_rule", rule.id, revision=rule.revision, cancelled_free=cancelled)
    _commit(db)
    return {"rule": rule_view(rule), "generation": generation, "cancelled_free": cancelled}


@router.delete("/availability-rules/{rule_id}")
def disable_rule(rule_id: str, user: User = Depends(require_active), db: Session = Depends(get_db)):
    actor_id = user.id
    _active(db, _lock_users(db, [actor_id])[actor_id], "mentor")
    rule = db.get(AvailabilityRule, rule_id, populate_existing=True)
    if not rule or rule.mentor_id != actor_id:
        raise HTTPException(404, "Правило расписания не найдено")
    cancelled = cancel_future_free(db, rule)
    rule.active, rule.updated_at = False, utcnow()
    _audit(db, actor_id, "availability.disabled", "availability_rule", rule.id, cancelled_free=cancelled)
    _commit(db)
    return {"rule": rule_view(rule), "cancelled_free": cancelled}


@router.post("/availability-rules/{rule_id}/regenerate")
def regenerate_rule(rule_id: str, user: User = Depends(require_active), db: Session = Depends(get_db)):
    actor_id = user.id
    _active(db, _lock_users(db, [actor_id])[actor_id], "mentor")
    rule = db.get(AvailabilityRule, rule_id, populate_existing=True)
    if not rule or rule.mentor_id != actor_id:
        raise HTTPException(404, "Правило расписания не найдено")
    if not rule.active:
        raise HTTPException(409, "Правило расписания отключено")
    generation = generate_rule(db, rule)
    _audit(db, actor_id, "availability.regenerated", "availability_rule", rule.id, created=generation["created"])
    _commit(db)
    return {"rule": rule_view(rule), "generation": generation}
