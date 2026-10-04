"""Versioned document administration, role changes and accountable support."""
import hashlib
from datetime import timedelta
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth import get_current_user, require_active, require_admin
from app.database import get_db
from app.models import (
    Application, AuditEvent, Booking, Consent, ConversationMember, Direction, Document,
    DocumentVersion, Message, Participation, Project, ProjectMember, Report,
    SessionToken, User, Notification, utcnow,
)
from app.models_support import ReportResponse
from app.routers.identity import audit, self_user
from app.transactions import lock_users


router = APIRouter()


class VersionInput(BaseModel):
    version: str = Field(min_length=1, max_length=40)
    content: str = Field(min_length=30, max_length=100000)
    content_kk: str | None = Field(default=None, min_length=30, max_length=100000)
    content_en: str | None = Field(default=None, min_length=30, max_length=100000)

    @field_validator("version", "content", "content_kk", "content_en", mode="before")
    @classmethod
    def trim(cls, value):
        return value.strip() if isinstance(value, str) else value


class DocumentInput(VersionInput):
    slug: str = Field(pattern=r"^[a-z][a-z0-9-]{1,79}$")
    title: str = Field(min_length=3, max_length=250)
    required_roles: list[Literal["mentee", "mentor", "admin"]] = Field(min_length=1, max_length=3)
    direction_id: str | None = None
    scope: Literal["registration", "intake", "private_project", "showcase"] = "registration"


class RoleInput(BaseModel):
    role: Literal["mentee", "mentor"]
    reason: str = Field(min_length=5, max_length=2000)

    @field_validator("reason", mode="before")
    @classmethod
    def trim(cls, value):
        return value.strip() if isinstance(value, str) else value


class ReportInput(BaseModel):
    entity_type: Literal["project", "mentor", "message", "booking", "support"]
    entity_id: str | None = Field(default=None, min_length=1, max_length=36)
    reason: str = Field(min_length=10, max_length=3000)

    @field_validator("reason", mode="before")
    @classmethod
    def trim(cls, value):
        return value.strip() if isinstance(value, str) else value


class ReportReview(BaseModel):
    status: Literal["reviewing", "resolved", "dismissed"]
    reason: str = Field(min_length=5, max_length=2000)

    @field_validator("reason", mode="before")
    @classmethod
    def trim(cls, value):
        return value.strip() if isinstance(value, str) else value


class ReportReply(BaseModel):
    body: str = Field(min_length=5, max_length=3000)

    @field_validator("body", mode="before")
    @classmethod
    def trim(cls, value):
        return value.strip() if isinstance(value, str) else value


def version_payload(document, version):
    return {
        "id": version.id, "document_id": document.id, "slug": document.slug,
        "title": document.title, "scope": document.scope,
        "required_roles": document.required_roles, "direction_id": document.direction_id,
        "active": document.active, "version": version.version, "content": version.content,
        "content_kk": version.content_kk, "content_en": version.content_en,
        "content_hash": version.content_hash, "published_at": version.published_at,
    }


@router.get("/admin/documents")
def all_documents(admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    output = []
    for document in db.scalars(select(Document).order_by(Document.title)).all():
        for version in db.scalars(select(DocumentVersion).where(DocumentVersion.document_id == document.id).order_by(DocumentVersion.published_at.desc())).all():
            output.append(version_payload(document, version))
    return output


@router.post("/admin/documents", status_code=201)
def create_document(payload: DocumentInput, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    if payload.direction_id:
        direction = db.get(Direction, payload.direction_id)
        if not direction or not direction.active:
            raise HTTPException(422, "Выберите действующее направление")
    document = Document(
        slug=payload.slug, title=payload.title.strip(),
        required_roles=list(dict.fromkeys(payload.required_roles)),
        direction_id=payload.direction_id, scope=payload.scope,
    )
    db.add(document)
    try:
        db.flush()
        version = DocumentVersion(document_id=document.id, version=payload.version, content=payload.content, content_kk=payload.content_kk, content_en=payload.content_en, content_hash=hashlib.sha256(payload.content.encode()).hexdigest())
        db.add(version)
        db.flush()
        audit(db, admin, "document.published", "document_version", version.id, {"slug": document.slug, "version": version.version})
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Документ с таким адресом уже существует")
    return version_payload(document, version)


@router.post("/admin/documents/{document_id}/versions", status_code=201)
def publish_version(document_id: str, payload: VersionInput, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    document = db.get(Document, document_id)
    if not document or not document.active:
        raise HTTPException(404, "Документ не найден")
    version = DocumentVersion(document_id=document_id, version=payload.version, content=payload.content, content_kk=payload.content_kk, content_en=payload.content_en, content_hash=hashlib.sha256(payload.content.encode()).hexdigest())
    db.add(version)
    try:
        db.flush()
        audit(db, admin, "document.version_published", "document_version", version.id, {"version": version.version})
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Версия с таким номером уже существует")
    return version_payload(document, version)


@router.get("/me/consents")
def consent_history(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    rows = db.execute(select(Consent, DocumentVersion, Document).join(DocumentVersion, DocumentVersion.id == Consent.document_version_id).join(Document, Document.id == DocumentVersion.document_id).where(Consent.user_id == user.id).order_by(Consent.accepted_at.desc())).all()
    return [{"id": consent.id, "title": document.title, "version": version.version, "content_hash": version.content_hash, "locale": consent.locale, "presented_content_hash": consent.presented_content_hash or version.content_hash, "accepted_at": consent.accepted_at, "method": consent.method} for consent, version, document in rows]


@router.get("/admin/users")
def users(q: str = Query(default="", max_length=160), limit: int = Query(default=50, ge=1, le=100), offset: int = Query(default=0, ge=0), admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    statement = select(User)
    if q:
        statement = statement.where(User.full_name.ilike(f"%{q}%") | User.email.ilike(f"%{q}%"))
    return [self_user(user) for user in db.scalars(statement.order_by(User.created_at.desc()).limit(limit).offset(offset)).all()]


@router.patch("/admin/users/{user_id}/role")
def change_role(user_id: str, payload: RoleInput, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    locked = lock_users(db, [user_id, admin.id])
    user = locked[user_id]
    if not user or user.role == "admin" or user.id == admin.id:
        raise HTTPException(409, "Эту роль нельзя изменить через пользовательскую форму")
    active = db.scalar(select(func.count(Participation.id)).where((Participation.mentee_id == user_id) | (Participation.mentor_id == user_id), Participation.status.in_(["active", "paused"])))
    if active:
        raise HTTPException(409, "Сначала завершите текущие участия пользователя")
    pending = db.scalar(select(func.count(Application.id)).where((Application.mentee_id == user_id) | (Application.mentor_id == user_id), Application.status == "pending"))
    scheduled = db.scalar(select(func.count(Booking.id)).where((Booking.mentee_id == user_id) | (Booking.mentor_id == user_id), Booking.status == "scheduled"))
    if pending or scheduled:
        raise HTTPException(409, "Сначала рассмотрите или отзовите заявки и отмените будущие встречи")
    if user.role == payload.role:
        return self_user(user)
    previous_role = user.role
    user.role = payload.role
    user.account_status = "draft"
    user.profile_completed = False
    user.intake_open = False
    user.mentor_commitment = False
    user.mentor_commitment_accepted_at = None
    db.execute(delete(SessionToken).where(SessionToken.user_id == user_id))
    audit(db, admin, "user.role_changed", "user", user.id, {"previous_role": previous_role, "role": payload.role, "reason": payload.reason.strip()})
    db.commit()
    return self_user(user)


def may_report(payload, user, db):
    if payload.entity_type == "support":
        return payload.entity_id == user.id
    if not payload.entity_id:
        return False
    if payload.entity_type == "project":
        project = db.get(Project, payload.entity_id)
        return project is not None and (project.visibility_status == "published" or project.owner_id == user.id or db.scalar(select(ProjectMember.id).where(ProjectMember.project_id == project.id, ProjectMember.user_id == user.id)) is not None)
    if payload.entity_type == "mentor":
        mentor = db.get(User, payload.entity_id)
        return mentor is not None and mentor.role == "mentor" and mentor.account_status == "active"
    if payload.entity_type == "message":
        message = db.get(Message, payload.entity_id)
        return message is not None and db.scalar(select(ConversationMember.id).where(ConversationMember.conversation_id == message.conversation_id, ConversationMember.user_id == user.id)) is not None
    booking = db.get(Booking, payload.entity_id)
    return booking is not None and user.id in {booking.mentee_id, booking.mentor_id}


@router.post("/reports", status_code=201)
def report(payload: ReportInput, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    actor_id = user.id
    user = lock_users(db, [actor_id])[actor_id]
    if user.account_status == "suspended":
        raise HTTPException(403, "Аккаунт недоступен")
    if payload.entity_type == "support":
        payload = payload.model_copy(update={"entity_id": user.id})
    else:
        require_active(user, db)
    if not may_report(payload, user, db):
        raise HTTPException(404, "Объект недоступен")
    count = db.scalar(select(func.count(Report.id)).where(Report.reporter_id == user.id, Report.created_at >= utcnow() - timedelta(days=1))) or 0
    if count >= 10:
        raise HTTPException(429, "За сутки можно отправить не больше 10 обращений")
    report = Report(reporter_id=user.id, **payload.model_dump())
    db.add(report)
    db.flush()
    audit(db, user, "report.created", "report", report.id)
    for admin_id in db.scalars(select(User.id).where(User.role == "admin", User.account_status == "active")):
        db.add(Notification(user_id=admin_id, kind="support_report", title="Новое обращение в поддержку", body="Откройте очередь обращений в админ-панели"))
    db.commit()
    return {"id": report.id, "status": report.status}


def report_view(report):
    return {"id": report.id, "entity_type": report.entity_type, "entity_id": report.entity_id,
        "reason": report.reason, "status": report.status, "created_at": report.created_at}


def response_view(row, user, db):
    sender = db.get(User, row.sender_id)
    return {"id": row.id, "report_id": row.report_id, "body": row.body, "created_at": row.created_at,
        "is_mine": row.sender_id == user.id, "sender_role": "support" if sender and sender.role == "admin" else "participant"}


def owned_report(db, report_id, user, admin=False):
    row = db.get(Report, report_id)
    if row is None or (not admin and row.reporter_id != user.id):
        raise HTTPException(404, "Обращение не найдено")
    return row


@router.get("/me/reports")
def own_reports(status: str | None = Query(None, pattern=r"^(pending|reviewing|resolved|dismissed)$"),
    limit: int = Query(25, ge=1, le=100), offset: int = Query(0, ge=0),
    user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    query = select(Report).where(Report.reporter_id == user.id)
    if status:
        query = query.where(Report.status == status)
    return [report_view(row) for row in db.scalars(query.order_by(Report.created_at.desc(), Report.id).limit(limit).offset(offset)).all()]


def report_messages(db, report_id, user, limit, offset, admin=False):
    owned_report(db, report_id, user, admin)
    rows = db.scalars(select(ReportResponse).where(ReportResponse.report_id == report_id)
        .order_by(ReportResponse.created_at.desc(), ReportResponse.id.desc()).limit(limit).offset(offset)).all()
    return [response_view(row, user, db) for row in reversed(rows)]


@router.get("/me/reports/{report_id}/messages")
def own_report_messages(report_id: str, limit: int = Query(50, ge=1, le=100), offset: int = Query(0, ge=0),
    user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return report_messages(db, report_id, user, limit, offset)


@router.get("/admin/reports/{report_id}/messages")
def administrative_report_messages(report_id: str, limit: int = Query(50, ge=1, le=100), offset: int = Query(0, ge=0),
    user: User = Depends(require_admin), db: Session = Depends(get_db)):
    return report_messages(db, report_id, user, limit, offset, True)


def add_report_reply(db, report_id, payload, user, admin=False):
    row = owned_report(db, report_id, user, admin)
    actor_id, reporter_id = user.id, row.reporter_id
    people = lock_users(db, [actor_id, reporter_id])
    user = people[actor_id]
    if user.account_status == "suspended" or (admin and (user.role != "admin" or user.account_status != "active")):
        raise HTTPException(403, "Аккаунт недоступен")
    row = db.scalar(select(Report).where(Report.id == report_id).with_for_update().execution_options(populate_existing=True))
    if row is None or (not admin and row.reporter_id != user.id):
        raise HTTPException(404, "Обращение не найдено")
    recent = db.scalar(select(func.count(ReportResponse.id)).where(ReportResponse.sender_id == user.id, ReportResponse.created_at >= utcnow() - timedelta(minutes=1))) or 0
    if recent >= 5:
        raise HTTPException(429, "Отправлено слишком много сообщений. Подождите минуту")
    message = ReportResponse(report_id=row.id, sender_id=user.id, body=payload.body)
    db.add(message)
    if not admin and row.status in {"resolved", "dismissed"}:
        row.status = "pending"
    db.flush()
    if admin:
        db.add(Notification(user_id=row.reporter_id, kind="support_reply", title="Поддержка ответила на обращение", body="Ответ доступен в разделе поддержки"))
    else:
        for administrator_id in db.scalars(select(User.id).where(User.role == "admin", User.account_status == "active")):
            db.add(Notification(user_id=administrator_id, kind="support_report", title="Новое сообщение по обращению", body="Откройте очередь обращений в админ-панели"))
    audit(db, user, "report.replied", "report", row.id, {"response_id": message.id, "status": row.status})
    db.commit()
    return response_view(message, user, db)


@router.post("/me/reports/{report_id}/messages", status_code=201)
def own_report_reply(report_id: str, payload: ReportReply, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return add_report_reply(db, report_id, payload, user)


@router.post("/admin/reports/{report_id}/messages", status_code=201)
def administrative_report_reply(report_id: str, payload: ReportReply, user: User = Depends(require_admin), db: Session = Depends(get_db)):
    return add_report_reply(db, report_id, payload, user, True)


@router.get("/admin/reports")
def reports(limit: int = Query(default=50, ge=1, le=100), offset: int = Query(default=0, ge=0), admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    return [{"id": report.id, "reporter_id": report.reporter_id, "entity_type": report.entity_type, "entity_id": report.entity_id, "reason": report.reason, "status": report.status, "created_at": report.created_at} for report in db.scalars(select(Report).order_by(Report.created_at.desc()).limit(limit).offset(offset)).all()]


@router.patch("/admin/reports/{report_id}")
def review_report(report_id: str, payload: ReportReview, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    report = db.get(Report, report_id)
    if not report:
        raise HTTPException(404, "Обращение не найдено")
    actor_id, reporter_id = admin.id, report.reporter_id
    people = lock_users(db, [actor_id, reporter_id])
    admin = people[actor_id]
    if admin.role != "admin" or admin.account_status != "active":
        raise HTTPException(403, "Доступ разрешён только администратору")
    report = db.scalar(select(Report).where(Report.id == report_id).with_for_update().execution_options(populate_existing=True))
    if not report:
        raise HTTPException(404, "Обращение не найдено")
    report.status = payload.status
    db.add(ReportResponse(report_id=report.id, sender_id=admin.id, body=payload.reason))
    db.add(Notification(user_id=report.reporter_id, kind="support_reply", title="Обновлён статус обращения", body="Решение и пояснение доступны в разделе поддержки"))
    audit(db, admin, "report.reviewed", "report", report.id, {"status": payload.status, "reason": payload.reason.strip()})
    db.commit()
    return {"id": report.id, "status": report.status}


@router.get("/admin/audit")
def audit_history(limit: int = Query(default=50, ge=1, le=100), offset: int = Query(default=0, ge=0), admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    return [{"id": event.id, "actor_id": event.actor_id, "action": event.action, "entity_type": event.entity_type, "entity_id": event.entity_id, "detail": event.detail, "created_at": event.created_at} for event in db.scalars(select(AuditEvent).order_by(AuditEvent.created_at.desc()).limit(limit).offset(offset)).all()]
