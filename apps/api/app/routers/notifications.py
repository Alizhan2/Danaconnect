"""Self-only notifications and factual, read-only enrollment guidance."""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, or_, select, update
from sqlalchemy.orm import Session

from app.auth import applicable_required_documents, current_required_versions, get_current_user, has_current_consents
from app.config import settings
from app.profile_state import admitted_profile
from app.database import get_db
from app.models import Application, Booking, Consent, Notification, Participation, Slot, User, utcnow


router = APIRouter(tags=["notifications"])


def notification_href(kind):
    # Stored bodies are participant text; never interpret them as navigation URLs.
    if kind.startswith("booking_") or kind == "booking_link":
        return "/calendar"
    return {"registration": "/onboarding", "application": "/dashboard", "mentor_offer": "/dashboard",
        "application_decision": "/dashboard", "application_withdrawn": "/dashboard",
        "participation": "/dashboard", "project_review": "/projects",
        "team_invitation": "/team", "message": "/messages",
        "support_report": "/admin", "support_reply": "/support"}.get(kind, "/notifications")


def notification_view(row):
    return {"id": row.id, "kind": row.kind, "title": row.title, "body": row.body,
        "read_at": row.read_at, "created_at": row.created_at, "href": notification_href(row.kind)}


@router.get("/notification-center")
def notifications(unread_only: bool = False, limit: int = Query(25, ge=1, le=100),
    offset: int = Query(0, ge=0), user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    query = select(Notification).where(Notification.user_id == user.id)
    if unread_only:
        query = query.where(Notification.read_at.is_(None))
    return [notification_view(row) for row in db.scalars(query.order_by(
        Notification.created_at.desc(), Notification.id.desc()).limit(limit).offset(offset)).all()]


@router.get("/notification-center/summary")
def summary(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return {"unread_count": db.scalar(select(func.count(Notification.id)).where(
        Notification.user_id == user.id, Notification.read_at.is_(None))) or 0}


@router.patch("/notification-center/{notification_id}/read")
def read_notification(notification_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    row = db.scalar(select(Notification).where(Notification.id == notification_id, Notification.user_id == user.id))
    if not row:
        raise HTTPException(404, "Уведомление не найдено")
    if row.read_at is None:
        db.execute(update(Notification).where(Notification.id == notification_id,
            Notification.user_id == user.id, Notification.read_at.is_(None)).values(read_at=utcnow()))
        db.commit()
        db.refresh(row)
    return notification_view(row)


@router.post("/notification-center/read-all")
def read_all(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    now = utcnow()
    result = db.execute(update(Notification).where(Notification.user_id == user.id,
        Notification.read_at.is_(None)).values(read_at=now))
    db.commit()
    return {"marked_count": result.rowcount, "read_at": now}


@router.get("/me/next-steps")
def next_steps(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    documents = applicable_required_documents(db, user)
    versions = current_required_versions(db, user)
    accepted = set(db.scalars(select(Consent.document_version_id).where(Consent.user_id == user.id)).all())
    pending_documents = sum(version.id not in accepted for version in versions)
    missing_documents = len(documents) != len(versions) or (
        settings.environment == "production" and user.role != "admin" and
        not any(document.scope == "registration" for document in documents))
    consents_current = has_current_consents(db, user)
    pending_applications = db.scalar(select(func.count(Application.id)).where(
        Application.status == "pending", or_(Application.mentee_id == user.id, Application.mentor_id == user.id))) or 0
    participation_counts = dict(db.execute(select(Participation.status, func.count(Participation.id)).where(
        Participation.status.in_(["active", "paused"]),
        or_(Participation.mentee_id == user.id, Participation.mentor_id == user.id)).group_by(Participation.status)).all())
    ongoing = sum(participation_counts.values())
    now = utcnow()
    upcoming_filter = (Booking.status == "scheduled", Slot.starts_at > now,
        or_(Booking.mentee_id == user.id, Booking.mentor_id == user.id))
    upcoming_count = db.scalar(select(func.count(Booking.id)).join(Slot, Slot.id == Booking.slot_id).where(*upcoming_filter)) or 0
    nearest = db.execute(select(Booking, Slot).join(Slot, Slot.id == Booking.slot_id).where(
        *upcoming_filter).order_by(Slot.starts_at, Booking.id).limit(1)).first()
    steps = []

    def add(identifier, title, description, href):
        steps.append({"id": identifier, "title": title, "description": description, "href": href})

    if user.role == "admin":
        add("administration", "Откройте административную панель", "Проверьте анкеты, проекты и состояние системы.", "/admin")
    else:
        if user.role == "unchosen" or not admitted_profile(user):
            add("profile", "Заполните профиль", "Выберите роль, направления и заполните обязательные поля анкеты.", "/onboarding")
        if user.account_status == "changes_requested":
            add("corrections", "Исправьте анкету", "В профиле доступен комментарий команды. После исправлений отправьте анкету повторно.", "/onboarding")
        if not consents_current and user.role != "unchosen":
            add("documents", "Проверьте обязательные документы",
                "Команда ещё не опубликовала все обязательные документы. Следите за обновлениями профиля." if missing_documents else
                "Прочитайте актуальные версии и сохраните подтверждение ознакомления.", "/onboarding")
        if user.account_status == "draft" and admitted_profile(user) and consents_current:
            add("submit", "Отправьте анкету на проверку", "Профиль заполнен. Отправьте анкету через раздел документов и согласий.", "/onboarding")
        if user.account_status == "pending":
            add("review", "Дождитесь проверки анкеты", "Анкета ожидает решения команды. Решение появится в уведомлениях и профиле.", "/onboarding")
        if user.account_status == "active" and admitted_profile(user) and consents_current:
            if pending_applications:
                add("applications", "Проверьте заявки", "Проверьте входящие предложения и статус отправленных заявок в кабинете.", "/dashboard")
            if user.role == "mentee" and not ongoing and not pending_applications:
                add("mentor", "Найдите ментора", "Выберите ментора в каталоге и отправьте заявку с описанием цели.", "/catalog")
            if user.role == "mentor" and not user.intake_open:
                add("intake", "Настройте приём участников", "Проверьте вместимость и откройте набор, когда будете готовы принимать заявки.", "/dashboard")
            if participation_counts.get("paused", 0):
                add("paused", "Проверьте участие на паузе", "Проверьте причину паузы и условия возобновления в рабочем пространстве.", "/dashboard")
            if participation_counts.get("active", 0) and not upcoming_count:
                add("calendar", "Проверьте расписание", "У вас есть текущее участие. Откройте календарь; новые встречи доступны для активного участия.", "/calendar")
    if upcoming_count:
        admitted = user.role == "admin" or (user.account_status == "active" and admitted_profile(user) and consents_current)
        add("meeting", "Подготовьтесь к ближайшей встрече",
            "Проверьте время, часовой пояс и актуальную ссылку в календаре." if admitted else
            "У вас запланирована встреча. Для доступа к календарю нужны одобренный профиль и актуальные согласия.",
            "/calendar" if admitted else "/onboarding")
    if not steps:
        add("workspace", "Откройте рабочее пространство", "Проверьте свои заявки, участия и результаты.", "/dashboard")
    return {"account_status": user.account_status, "role": user.role,
        "profile_completed": admitted_profile(user), "consents_current": consents_current,
        "pending_documents": pending_documents, "documents_unavailable": missing_documents,
        "intake_open": user.intake_open, "pending_applications": pending_applications,
        "ongoing_participations": ongoing, "paused_participations": participation_counts.get("paused", 0), "upcoming_bookings": upcoming_count,
        "nearest_meeting": {"id": nearest[0].id, "starts_at": nearest[1].starts_at,
            "ends_at": nearest[1].ends_at, "timezone": nearest[1].timezone} if nearest else None,
        "steps": steps}
