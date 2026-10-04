"""Administrative lifecycle and self-service data access."""
from typing import Literal
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session
from app.auth import get_current_user, has_current_consents, require_admin
from app.config import settings
from app.profile_state import admitted_profile
from app.database import get_db
from app.models import (Application, Booking, Consent, Document, DocumentVersion,
    Feedback, Message, Notification, Participation, Project, RegistrationReview,
    Result, SessionToken, Slot, User, utcnow)
from app.models_privacy import PrivacyRequest
from app.routers.identity import audit, self_user
from app.transactions import lock_users
from app.booking_lifecycle import cancel_reservation

router = APIRouter()


class StatusInput(BaseModel):
    status: Literal["active", "suspended"]
    reason: str = Field(min_length=5, max_length=2000)

    @field_validator("reason", mode="before")
    @classmethod
    def trim(cls, value):
        return value.strip() if isinstance(value, str) else value


class DocumentMetadata(BaseModel):
    active: bool | None = None
    title: str | None = Field(default=None, min_length=3, max_length=250)

    @field_validator("title", mode="before")
    @classmethod
    def trim(cls, value):
        return value.strip() if isinstance(value, str) else value


def suspend_account(db, user, actor, reason):
    user.account_status = "suspended"
    user.intake_open = False
    db.execute(delete(SessionToken).where(SessionToken.user_id == user.id))
    for project in db.scalars(select(Project).where(Project.owner_id == user.id,
        Project.visibility_status.in_(["published", "pending"]))):
        project.visibility_status = "hidden"
        audit(db, actor, "project.hidden_by_account_status", "project", project.id)
    meetings = db.execute(select(Booking, Slot).join(Slot, Slot.id == Booking.slot_id)
        .where(Booking.status == "scheduled", Slot.starts_at > utcnow(),
            (Booking.mentee_id == user.id) | (Booking.mentor_id == user.id))
        .with_for_update()).all()
    for booking, slot in meetings:
        cancel_reservation(db, booking, disable_slot=slot.mentor_id == user.id)
        peer_id = booking.mentee_id if booking.mentor_id == user.id else booking.mentor_id
        db.add(Notification(user_id=peer_id, kind="booking_cancelled",
            title="Встреча отменена", body="Аккаунт одного из участников недоступен. Выберите другое время или ментора."))
        audit(db, actor, "booking.cancelled_by_account_status", "booking", booking.id)
    for slot in db.scalars(select(Slot).where(Slot.mentor_id == user.id,
        Slot.starts_at > utcnow(), Slot.status == "available")).all():
        slot.status = "cancelled"
    audit(db, actor, "user.suspended", "user", user.id, {"reason": reason})


@router.get("/admin/me")
def administrator(admin: User = Depends(require_admin)):
    return self_user(admin)


@router.patch("/admin/users/{user_id}/status")
def account_status(user_id: str, payload: StatusInput,
    admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    user = lock_users(db, [user_id, admin.id])[user_id]
    if user.role == "admin" or user.id == admin.id:
        raise HTTPException(409, "Учётную запись администратора нельзя изменять этой формой")
    if user.account_status == payload.status:
        return self_user(user)
    if payload.status == "suspended":
        suspend_account(db, user, admin, payload.reason)
    else:
        review = db.scalar(select(RegistrationReview).where(RegistrationReview.user_id == user.id)
            .order_by(RegistrationReview.created_at.desc(), RegistrationReview.id.desc()).limit(1))
        if user.account_status != "suspended" or not admitted_profile(user) or not review or review.decision != "approved":
            raise HTTPException(409, "Возобновить можно только ранее одобренный аккаунт. Для анкеты используйте очередь модерации")
        if not has_current_consents(db, user):
            # Allow login and consent renewal, but never restore active access yet.
            user.account_status = "pending"
            audit(db, admin, "user.reactivation_pending_consents", "user", user.id, {"reason": payload.reason})
        else:
            user.account_status = "active"
            audit(db, admin, "user.reactivated", "user", user.id, {"reason": payload.reason})
    db.commit()
    return self_user(user)


@router.patch("/admin/documents/{document_id}")
def document_metadata(document_id: str, payload: DocumentMetadata,
    admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    document = db.scalar(select(Document).where(Document.id == document_id).with_for_update())
    if not document:
        raise HTTPException(404, "Документ не найден")
    changes = payload.model_dump(exclude_none=True)
    if not changes:
        raise HTTPException(422, "Укажите название или статус документа")
    for key, value in changes.items():
        setattr(document, key, value)
    audit(db, admin, "document.metadata_changed", "document", document.id, changes)
    db.commit()
    return {"id": document.id, "title": document.title, "active": document.active}


@router.get("/admin/operations")
def operations(admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    from app.delivery import delivery_ready, google_ready
    from app.models_delivery import AdminCredential
    from app.models_operations import WorkerHeartbeat
    from app.services.operations_snapshot import delivery_snapshot, operations_signals, worker_snapshot
    from app.storage import storage_ready
    observed_at = utcnow()
    heartbeat = db.get(WorkerHeartbeat, "calendar")
    delivery = delivery_snapshot(db, observed_at)
    worker = worker_snapshot(heartbeat, observed_at)
    email_configured = delivery_ready()
    published_documents = db.execute(select(Document, DocumentVersion.id).join(
        DocumentVersion, DocumentVersion.document_id == Document.id).where(Document.active.is_(True))).all()
    legal_configured = all(any(document.scope == scope and (not document.required_roles or role in document.required_roles)
        and document.direction_id is None for document, _ in published_documents)
        for role, scope in (("mentee", "registration"), ("mentor", "registration"), ("mentor", "private_project")))
    worker_recent = worker["recent_success"]
    counts = {"users": db.scalar(select(func.count(User.id))),
        "registrations_pending": db.scalar(select(func.count(User.id)).where(User.account_status == "pending")),
        "privacy_pending": db.scalar(select(func.count(PrivacyRequest.id)).where(PrivacyRequest.status.in_(["pending", "reviewing"]))),
        "email_pending": delivery["status_counts"]["pending"] + delivery["status_counts"]["leased"],
        "email_failed": delivery["status_counts"]["failed"]}
    return {"environment": settings.environment, "demo_mode": settings.demo_mode, "observed_at": observed_at,
        "readiness": {"postgresql": db.get_bind().dialect.name == "postgresql",
            "email_configured": email_configured, "google_configured": google_ready(),
            "https_origins": bool(settings.trusted_origins) and all(x.startswith("https://") for x in settings.trusted_origins),
            "admin_mfa": not bool(db.scalar(select(User.id).outerjoin(AdminCredential,
                (AdminCredential.user_id == User.id) & AdminCredential.active.is_(True)).where(
                    User.role == "admin", User.account_status == "active", AdminCredential.id.is_(None)).limit(1))),
            "demo_disabled": not settings.demo_mode, "debug_codes_disabled": not settings.auth_debug_code,
            "private_storage_configured": storage_ready(), "legal_documents_configured": legal_configured,
            "worker_recent_success": worker_recent},
        "counts": counts,
        "worker": worker, "delivery": delivery,
        "signals": operations_signals(delivery, worker, email_configured=email_configured,
            heartbeat_present=heartbeat is not None)}


def request_payload(row):
    return {key: getattr(row, key) for key in ("id", "user_id", "kind", "status", "reason", "review_reason", "created_at", "reviewed_at")}


class PrivacyInput(BaseModel):
    kind: Literal["export", "deactivate", "erase"]
    reason: str = Field(default="", max_length=2000)


class PrivacyReview(StatusInput):
    status: Literal["reviewing", "fulfilled", "rejected"]


@router.get("/me/privacy-requests")
def own_requests(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return [request_payload(row) for row in db.scalars(select(PrivacyRequest)
        .where(PrivacyRequest.user_id == user.id).order_by(PrivacyRequest.created_at.desc())).all()]


@router.post("/me/privacy-requests", status_code=201)
def create_request(payload: PrivacyInput, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    user = lock_users(db, [user.id])[user.id]
    existing = db.scalar(select(PrivacyRequest).where(PrivacyRequest.user_id == user.id,
        PrivacyRequest.kind == payload.kind, PrivacyRequest.status.in_(["pending", "reviewing"])))
    if existing:
        return request_payload(existing)
    row = PrivacyRequest(user_id=user.id, kind=payload.kind, reason=payload.reason.strip())
    db.add(row)
    db.flush()
    audit(db, user, "privacy.requested", "privacy_request", row.id, {"kind": row.kind})
    db.commit()
    return request_payload(row)


@router.get("/admin/privacy-requests")
def privacy_queue(limit: int = Query(50, ge=1, le=100), offset: int = Query(0, ge=0),
    admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    return [request_payload(row) for row in db.scalars(select(PrivacyRequest)
        .order_by(PrivacyRequest.created_at.desc()).limit(limit).offset(offset)).all()]


@router.patch("/admin/privacy-requests/{request_id}")
def review_privacy(request_id: str, payload: PrivacyReview,
    admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    row = db.get(PrivacyRequest, request_id)
    if not row:
        raise HTTPException(404, "Запрос не найден")
    request_user_id = row.user_id
    people = lock_users(db, [request_user_id, admin.id])
    row = db.get(PrivacyRequest, request_id, populate_existing=True)
    if row.status in {"fulfilled", "rejected"}:
        raise HTTPException(409, "Запрос уже рассмотрен")
    if row.kind == "erase" and payload.status == "fulfilled":
        raise HTTPException(409, "Удаление требует отдельной процедуры очистки и проверки обязательных сроков хранения. Отметить его выполненным этой формой нельзя")
    if row.kind == "deactivate" and payload.status == "fulfilled":
        user = people[request_user_id]
        if user.role == "admin":
            raise HTTPException(409, "Запрос администратора требует передачи управления другому администратору")
        suspend_account(db, user, admin, payload.reason)
    row.status, row.review_reason = payload.status, payload.reason
    row.reviewed_by, row.reviewed_at = admin.id, utcnow()
    audit(db, admin, "privacy.reviewed", "privacy_request", row.id, {"status": row.status, "reason": payload.reason})
    db.commit()
    return request_payload(row)


def own_rows(db, model, condition, keys):
    return [{key: getattr(row, key) for key in keys} for row in db.scalars(select(model).where(condition)).all()]


@router.get("/me/data-export")
def data_export(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    from app.routers.projects import application_initiation
    from app.models_collaboration import PrivateAttachment, ProjectComment, TeamInvitation
    from app.models_growth import GrowthAward, GrowthPrivacy, PointEvent
    from app.models_ai import AIPreference, AIProposal
    from app.models_support import ReportResponse
    from app.models_engagement import MessageRead
    from app.models import Report
    account = self_user(user)
    account.pop("has_current_consents", None)
    consents = db.execute(select(Consent, DocumentVersion, Document)
        .join(DocumentVersion, DocumentVersion.id == Consent.document_version_id)
        .join(Document, Document.id == DocumentVersion.document_id).where(Consent.user_id == user.id)).all()
    participation_ids = select(Participation.id).where((Participation.mentee_id == user.id) | (Participation.mentor_id == user.id))
    application_fields = ("id", "project_id", "mentee_id", "mentor_id", "motivation", "status", "created_at")
    application_rows = [{**{key: getattr(row, key) for key in application_fields}, **application_initiation(row)}
        for row in db.scalars(select(Application).where(
            (Application.mentee_id == user.id) | (Application.mentor_id == user.id))
            .order_by(Application.created_at.desc(), Application.id)).all()]
    return {"exported_at": utcnow(), "account": account,
        "consents": [{"document": document.title, "version": version.version, "accepted_at": consent.accepted_at,
            "locale": consent.locale, "content_hash": consent.presented_content_hash or version.content_hash,
            "content": getattr(version, f"content_{consent.locale}", None) or version.content} for consent, version, document in consents],
        "projects": own_rows(db, Project, Project.owner_id == user.id, ["id", "title", "problem", "description", "private_details", "stage", "created_at"]),
        "applications": application_rows,
        "participations": own_rows(db, Participation, (Participation.mentee_id == user.id) | (Participation.mentor_id == user.id), ["id", "project_id", "status", "started_at", "completed_at"]),
        "bookings": own_rows(db, Booking, (Booking.mentee_id == user.id) | (Booking.mentor_id == user.id), ["id", "slot_id", "status", "meeting_url", "created_at"]),
        "results": own_rows(db, Result, Result.participation_id.in_(participation_ids), ["id", "participation_id", "status", "summary", "artifact_url", "completed_at"]),
        "feedback_authored": own_rows(db, Feedback, Feedback.author_id == user.id, ["id", "participation_id", "rating", "nps", "comment", "created_at"]),
        "messages_authored": own_rows(db, Message, Message.sender_id == user.id, ["id", "conversation_id", "body", "created_at"]),
        "comments_authored": own_rows(db, ProjectComment, ProjectComment.author_id == user.id, ["id", "project_id", "body", "scope", "status", "created_at"]),
        "attachment_metadata": own_rows(db, PrivateAttachment, PrivateAttachment.uploader_id == user.id, ["id", "project_id", "filename", "content_type", "size_bytes", "sha256", "status", "created_at"]),
        "invitations": own_rows(db, TeamInvitation, (TeamInvitation.inviter_id == user.id) | (TeamInvitation.target_email == user.email), ["id", "project_id", "member_role", "status", "expires_at", "created_at"]),
        "earned_points": own_rows(db, PointEvent, PointEvent.user_id == user.id, ["id", "source_type", "source_id", "points", "earned_at"]),
        "leaderboard_preferences": own_rows(db, GrowthPrivacy, GrowthPrivacy.user_id == user.id, ["leaderboard_visible", "alias", "consent_version", "accepted_at", "updated_at"]),
        "awards": own_rows(db, GrowthAward, GrowthAward.user_id == user.id, ["id", "kind", "title_ru", "title_kk", "title_en", "description_ru", "description_kk", "description_en", "issued_name", "issued_at", "revoked_at", "revocation_reason"]),
        "ai_preferences": own_rows(db, AIPreference, AIPreference.user_id == user.id, ["allow_admin_review", "updated_at"]),
        "ai_proposals": own_rows(db, AIProposal, (AIProposal.requester_id == user.id) | (AIProposal.subject_user_id == user.id), ["id", "kind", "model", "status", "proposal", "review_reason", "override_summary", "created_at", "decided_at"]),
        "support_requests": own_rows(db, Report, Report.reporter_id == user.id, ["id", "entity_type", "entity_id", "reason", "status", "created_at"]),
        "support_messages_authored": own_rows(db, ReportResponse, ReportResponse.sender_id == user.id, ["id", "report_id", "body", "created_at"]),
        "message_read_receipts": own_rows(db, MessageRead, MessageRead.user_id == user.id, ["message_id", "read_at"]),
        "privacy_requests": [request_payload(row) for row in db.scalars(select(PrivacyRequest).where(PrivacyRequest.user_id == user.id)).all()]}
