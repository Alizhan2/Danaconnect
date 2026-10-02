"""Moderated public comments and NDA-gated private project collaboration."""
import hashlib
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, Request, UploadFile, File
from fastapi.responses import Response
from sqlalchemy import func, or_, select, update
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session

from app.auth import get_current_user, has_current_consents, require_active, require_admin
from app.config import settings
from app.database import get_db
from app.delivery import DeliveryUnavailable, enqueue_email
from app.models import AuditEvent, Consent, Direction, Document, DocumentVersion, Notification, Participation, Project, ProjectMember, User, utcnow
from app.models_collaboration import PrivateAttachment, ProjectComment, TeamInvitation
from app.models_delivery import EmailOutbox
from app.schemas.collaboration import CommentInput, CommentReview, InvitationDecision, InvitationInput, TeamRemovalInput
from app.storage import InvalidAttachment, StorageUnavailable, TYPES, delete_private, download_disposition, inspect_attachment, put_private, read_private, storage_ready
from app.transactions import lock_users
from app.project_capacity import project_occupied


router = APIRouter(tags=["collaboration"])


def commit(db):
    try:
        db.commit()
    except (IntegrityError, OperationalError):
        db.rollback()
        raise HTTPException(409, "Данные команды изменились. Обновите страницу и повторите действие") from None


def audit(db, user, action, entity_type, entity_id, detail=None):
    db.add(AuditEvent(actor_id=user.id, action=action, entity_type=entity_type, entity_id=entity_id, detail=detail or {}))


def member(db, project, user):
    return user.id in {project.owner_id, project.mentor_id} or db.scalar(select(ProjectMember.id).where(ProjectMember.project_id == project.id, ProjectMember.user_id == user.id)) is not None


def private_permission(db, project, user, *, allow_invitee=False):
    if user.account_status != "active" or (user.role != "admin" and not user.profile_completed) or not has_current_consents(db, user):
        raise HTTPException(403, "Аккаунт не допущен к закрытым материалам")
    if user.role != "admin" and not member(db, project, user) and not allow_invitee:
        raise HTTPException(404, "Нет доступа к закрытым материалам проекта")
    versions = []
    for document in db.scalars(select(Document).where(Document.active.is_(True), Document.scope == "private_project")).all():
        if document.required_roles and user.role not in document.required_roles:
            continue
        if document.direction_id and document.direction_id != project.direction_id:
            continue
        version = db.scalar(select(DocumentVersion).where(DocumentVersion.document_id == document.id).order_by(DocumentVersion.published_at.desc(), DocumentVersion.id.desc()).limit(1))
        if version is None:
            raise HTTPException(503, "Обязательный NDA ещё не опубликован")
        versions.append(version.id)
    if user.role == "mentor" and settings.environment == "production" and not versions:
        raise HTTPException(503, "Для доступа ментора необходимо опубликовать актуальный NDA")
    accepted = set(db.scalars(select(Consent.document_version_id).where(Consent.user_id == user.id)).all())
    if not set(versions) <= accepted:
        raise HTTPException(403, "Для закрытых материалов подтвердите актуальный NDA")


def get_project(db, project_id, user, *, private=False):
    project = db.get(Project, project_id)
    if not project:
        raise HTTPException(404, "Проект не найден")
    if private:
        private_permission(db, project, user)
    elif project.visibility_status != "published" and user.role != "admin" and not member(db, project, user):
        raise HTTPException(404, "Проект не найден")
    return project


def lock_project(db, project_id):
    # User serialization is acquired first; then all team-capacity writes share
    # the project row lock with application acceptance in the original router.
    changed = db.execute(update(Project).where(Project.id == project_id).values(capacity=Project.capacity))
    if changed.rowcount != 1:
        raise HTTPException(404, "Проект не найден")
    return db.get(Project, project_id, populate_existing=True)


def team_occupied(db, project):
    return project_occupied(db, project)


def comment_view(db, comment):
    author = db.get(User, comment.author_id)
    return {"id": comment.id, "project_id": comment.project_id, "author_id": comment.author_id, "author_name": author.full_name if author and author.account_status == "active" else "Участник", "scope": comment.scope, "status": comment.status, "body": comment.body, "created_at": comment.created_at}


@router.get("/projects/{project_id}/comments")
def comments(project_id: str, scope: str = Query("public", pattern=r"^(public|team)$"), limit: int = Query(50, ge=1, le=100), offset: int = Query(0, ge=0), user: User = Depends(require_active), db: Session = Depends(get_db)):
    get_project(db, project_id, user, private=scope == "team")
    statement = select(ProjectComment).where(ProjectComment.project_id == project_id, ProjectComment.scope == scope)
    if scope == "public":
        statement = statement.where(or_(ProjectComment.status == "visible", (ProjectComment.author_id == user.id) & (ProjectComment.status == "pending")))
    else:
        statement = statement.where(ProjectComment.status == "visible")
    rows = db.scalars(statement.order_by(ProjectComment.created_at, ProjectComment.id).limit(limit).offset(offset)).all()
    return [comment_view(db, row) for row in rows]


@router.post("/projects/{project_id}/comments", status_code=201)
def post_comment(project_id: str, payload: CommentInput, user: User = Depends(require_active), db: Session = Depends(get_db)):
    from app.services.action_limits import enforce_action_limit
    actor_id = user.id
    user = lock_users(db, [actor_id])[actor_id]
    require_active(user, db)
    if user.role not in {"mentor", "mentee", "admin"} or user.account_status != "active" or not has_current_consents(db, user):
        raise HTTPException(403, "Аккаунт не допущен к обсуждению")
    project = get_project(db, project_id, user, private=payload.scope == "team")
    if payload.scope == "public" and project.visibility_status != "published":
        raise HTTPException(409, "Публичное обсуждение доступно после публикации проекта")
    enforce_action_limit(db, actor_id, "comment.created")
    comment = ProjectComment(project_id=project.id, author_id=user.id, body=payload.body, scope=payload.scope, status="pending" if payload.scope == "public" else "visible")
    db.add(comment)
    db.flush()
    audit(db, user, "comment.created", "project_comment", comment.id, {"scope": comment.scope})
    commit(db)
    return comment_view(db, comment)


@router.delete("/comments/{comment_id}")
def remove_comment(comment_id: str, user: User = Depends(require_active), db: Session = Depends(get_db)):
    comment = db.get(ProjectComment, comment_id)
    if not comment:
        raise HTTPException(404, "Комментарий не найден")
    project = get_project(db, comment.project_id, user, private=comment.scope == "team")
    if user.id not in {comment.author_id, project.owner_id} and user.role != "admin":
        raise HTTPException(404, "Комментарий не найден")
    comment.status = "hidden"
    audit(db, user, "comment.hidden", "project_comment", comment.id)
    commit(db)
    return {"id": comment.id, "status": comment.status}


@router.get("/admin/comments")
def comment_queue(limit: int = Query(50, ge=1, le=100), offset: int = Query(0, ge=0), admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    rows = db.scalars(select(ProjectComment).where(ProjectComment.scope == "public", ProjectComment.status == "pending").order_by(ProjectComment.created_at).limit(limit).offset(offset)).all()
    return [comment_view(db, row) for row in rows]


@router.post("/admin/comments/{comment_id}/review")
def review_comment(comment_id: str, payload: CommentReview, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    comment = db.get(ProjectComment, comment_id)
    if not comment or comment.scope != "public":
        raise HTTPException(404, "Публичный комментарий не найден")
    project = db.get(Project, comment.project_id)
    if payload.decision == "visible" and (not project or project.visibility_status != "published"):
        raise HTTPException(409, "Проект должен быть опубликован")
    comment.status, comment.moderation_reason = payload.decision, payload.reason
    audit(db, admin, "comment.reviewed", "project_comment", comment.id, {"decision": payload.decision, "reason": payload.reason})
    commit(db)
    return comment_view(db, comment)


def invitation_view(db, invitation, user):
    project = db.get(Project, invitation.project_id)
    return {"id": invitation.id, "project_id": invitation.project_id, "project_title": project.title if project else "", "inviter_id": invitation.inviter_id, "target_email": invitation.target_email, "member_role": invitation.member_role, "status": invitation.status, "expires_at": invitation.expires_at, "created_at": invitation.created_at, "incoming": invitation.target_email == user.email, "email_queued": bool(invitation.email_outbox_id)}


@router.get("/team-invitations")
def list_invitations(limit: int = Query(50, ge=1, le=100), offset: int = Query(0, ge=0), user: User = Depends(require_active), db: Session = Depends(get_db)):
    own_projects = select(Project.id).where(or_(Project.owner_id == user.id, Project.mentor_id == user.id))
    visible = or_(TeamInvitation.target_email == user.email, TeamInvitation.inviter_id == user.id, TeamInvitation.project_id.in_(own_projects))
    db.execute(update(TeamInvitation).where(visible, TeamInvitation.status == "pending", TeamInvitation.expires_at <= utcnow()).values(status="expired", decided_at=utcnow()))
    commit(db)
    rows = db.scalars(select(TeamInvitation).where(visible).order_by(TeamInvitation.created_at.desc()).limit(limit).offset(offset)).all()
    return [invitation_view(db, row, user) for row in rows]


@router.post("/projects/{project_id}/invitations", status_code=201)
def create_invitation(project_id: str, payload: InvitationInput, user: User = Depends(require_active), db: Session = Depends(get_db)):
    user = lock_users(db, [user.id])[user.id]
    project = lock_project(db, project_id)
    if user.id not in {project.owner_id, project.mentor_id}:
        raise HTTPException(404, "Свой проект не найден")
    private_permission(db, project, user)
    if project.visibility_status != "published":
        raise HTTPException(409, "Приглашения доступны после публикации проекта")
    if payload.email == user.email:
        raise HTTPException(409, "Вы уже состоите в проекте")
    target = db.scalar(select(User).where(User.email == payload.email))
    if target and member(db, project, target):
        raise HTTPException(409, "Участник уже состоит в проекте")
    db.execute(update(TeamInvitation).where(TeamInvitation.project_id == project.id, TeamInvitation.status == "pending", TeamInvitation.expires_at <= utcnow()).values(status="expired", decided_at=utcnow()))
    duplicate = db.scalar(select(TeamInvitation).where(TeamInvitation.project_id == project.id, TeamInvitation.target_email == payload.email, TeamInvitation.status == "pending"))
    if duplicate:
        return invitation_view(db, duplicate, user)
    pending = db.scalar(select(func.count(TeamInvitation.id)).where(TeamInvitation.project_id == project.id, TeamInvitation.status == "pending"))
    if pending >= 50 or team_occupied(db, project) >= project.capacity:
        raise HTTPException(409, "Нет мест или достигнут лимит ожидающих приглашений")
    invitation = TeamInvitation(project_id=project.id, inviter_id=user.id, target_email=payload.email, expires_at=utcnow() + timedelta(days=payload.expires_in_days))
    db.add(invitation)
    db.flush()
    if target:
        db.add(Notification(user_id=target.id, kind="team_invitation", title="Приглашение в команду проекта", body=project.title))
    locale = getattr(target, "preferred_locale", getattr(user, "preferred_locale", "ru"))
    titles = {"ru": "Приглашение в команду DanaConnect", "kk": "DanaConnect командасына шақыру", "en": "DanaConnect team invitation"}
    bodies = {"ru": "Вас пригласили в команду проекта. Войдите с этим email и откройте раздел команды. Приглашение не создаёт участие автоматически.", "kk": "Сіз жоба командасына шақырылдыңыз. Осы email арқылы кіріп, команда бөлімін ашыңыз. Шақыру қатысуды автоматты түрде жасамайды.", "en": "You were invited to a project team. Sign in with this email and open the team page. An invitation does not automatically enroll you in mentorship."}
    try:
        email = enqueue_email(db, payload.email, titles.get(locale, titles["ru"]), bodies.get(locale, bodies["ru"]) + "\n" + settings.frontend_url.rstrip("/") + "/team", dedup_key="team-invitation:" + invitation.id, locale=locale, expires_at=invitation.expires_at)
        invitation.email_outbox_id = email.id
    except DeliveryUnavailable:
        pass
    audit(db, user, "team.invited", "team_invitation", invitation.id)
    commit(db)
    return invitation_view(db, invitation, user)


@router.post("/team-invitations/{invitation_id}/decision")
def decide_invitation(invitation_id: str, payload: InvitationDecision, user: User = Depends(require_active), db: Session = Depends(get_db)):
    invitation = db.get(TeamInvitation, invitation_id)
    if not invitation or invitation.target_email != user.email:
        raise HTTPException(404, "Приглашение не найдено")
    project_id = invitation.project_id
    user = lock_users(db, [user.id])[user.id]
    project = lock_project(db, project_id)
    invitation = db.get(TeamInvitation, invitation_id, populate_existing=True)
    if invitation.status != "pending":
        if invitation.status == payload.decision:
            return invitation_view(db, invitation, user)
        raise HTTPException(409, "Приглашение уже обработано")
    if invitation.expires_at <= utcnow():
        invitation.status, invitation.decided_at = "expired", utcnow()
        commit(db)
        raise HTTPException(409, "Срок приглашения истёк")
    if payload.decision == "accepted":
        if user.role not in {"mentor", "mentee"} or user.account_status != "active" or not has_current_consents(db, user):
            raise HTTPException(403, "Заполните анкету и подтвердите документы")
        direction = db.get(Direction, project.direction_id)
        if project.visibility_status != "published" or not direction or not direction.active:
            raise HTTPException(409, "Проект недоступен для присоединения")
        if project.direction_id not in (user.direction_ids or []):
            raise HTTPException(409, "Направление проекта должно быть в вашей анкете")
        private_permission(db, project, user, allow_invitee=True)
        if not member(db, project, user):
            if team_occupied(db, project) >= project.capacity:
                raise HTTPException(409, "В команде нет свободных мест")
            db.add(ProjectMember(project_id=project.id, user_id=user.id, member_role="collaborator"))
    invitation.status, invitation.decided_at = payload.decision, utcnow()
    invitation.accepted_by = user.id if payload.decision == "accepted" else None
    audit(db, user, "team.invitation_decided", "team_invitation", invitation.id, {"decision": payload.decision})
    commit(db)
    return invitation_view(db, invitation, user)


@router.post("/team-invitations/{invitation_id}/revoke")
def revoke_invitation(invitation_id: str, user: User = Depends(require_active), db: Session = Depends(get_db)):
    invitation = db.get(TeamInvitation, invitation_id)
    if not invitation:
        raise HTTPException(404, "Приглашение не найдено")
    project_id = invitation.project_id
    user = lock_users(db, [user.id])[user.id]
    project = lock_project(db, project_id)
    private_permission(db, project, user)
    invitation = db.get(TeamInvitation, invitation_id, populate_existing=True)
    if user.id not in {project.owner_id, project.mentor_id}:
        raise HTTPException(404, "Приглашение не найдено")
    if invitation.status != "pending":
        raise HTTPException(409, "Можно отозвать только ожидающее приглашение")
    invitation.status, invitation.decided_at = "revoked", utcnow()
    if invitation.email_outbox_id:
        db.execute(update(EmailOutbox).where(EmailOutbox.id == invitation.email_outbox_id, EmailOutbox.status.in_(["pending", "leased"])).values(status="failed", encrypted_payload="", lease_token=None, lease_until=None, last_error_code="invitation_revoked"))
    audit(db, user, "team.invitation_revoked", "team_invitation", invitation.id)
    commit(db)
    return invitation_view(db, invitation, user)


@router.get("/me/team-memberships")
def own_team_memberships(limit: int = Query(50, ge=1, le=100), offset: int = Query(0, ge=0),
    user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    rows = db.execute(select(ProjectMember, Project).join(Project, Project.id == ProjectMember.project_id)
        .where(ProjectMember.user_id == user.id).order_by(ProjectMember.joined_at.desc(), ProjectMember.id)
        .limit(limit).offset(offset)).all()
    result = []
    for membership, project in rows:
        ongoing = db.scalar(select(Participation.id).where(Participation.project_id == project.id,
            Participation.mentee_id == user.id, Participation.status.in_(["active", "paused"])).limit(1))
        can_leave = membership.member_role == "collaborator" and user.id not in {project.owner_id, project.mentor_id} and not ongoing
        result.append({"project_id": project.id, "title": project.title, "member_role": membership.member_role, "can_leave": bool(can_leave)})
    return result


@router.get("/projects/{project_id}/team")
def project_team(project_id: str, user: User = Depends(require_active), db: Session = Depends(get_db)):
    project = get_project(db, project_id, user, private=True)
    rows = db.execute(select(ProjectMember, User).join(User, User.id == ProjectMember.user_id).where(ProjectMember.project_id == project.id).order_by(ProjectMember.joined_at).limit(100)).all()
    result = [{"user_id": person.id, "full_name": person.full_name, "role": person.role, "member_role": membership.member_role, "active": person.account_status == "active"} for membership, person in rows]
    listed = {item["user_id"] for item in result}
    for identifier in [project.owner_id, project.mentor_id]:
        if identifier and identifier not in listed:
            person = db.get(User, identifier)
            if person:
                result.append({"user_id": person.id, "full_name": person.full_name, "role": person.role, "member_role": "owner" if identifier == project.owner_id else "mentor", "active": person.account_status == "active"})
    ongoing = set(db.scalars(select(Participation.mentee_id).where(Participation.project_id == project.id, Participation.status.in_(["active", "paused"]))).all())
    manages = user.role == "admin" or user.id in {project.owner_id, project.mentor_id}
    for item in result:
        removable = item["member_role"] == "collaborator" and item["user_id"] not in {project.owner_id, project.mentor_id} and item["user_id"] not in ongoing
        item["is_self_leave"] = item["user_id"] == user.id
        item["can_remove"] = removable and (manages or item["is_self_leave"])
    return result


@router.post("/projects/{project_id}/team/{user_id}/remove")
def remove_team_member(project_id: str, user_id: str, payload: TeamRemovalInput, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    actor_id = user.id
    # Match the capacity-changing join/acceptance paths: acquire sorted user
    # rows before the project row, then reread all permissions and membership.
    locked = lock_users(db, [actor_id, user_id])
    user = locked[actor_id]
    project = lock_project(db, project_id)
    if user.account_status == "suspended":
        raise HTTPException(403, "Аккаунт недоступен")
    is_self = actor_id == user_id
    if not is_self:
        if user.role != "admin" and actor_id not in {project.owner_id, project.mentor_id}:
            raise HTTPException(404, "Участник команды не найден")
        private_permission(db, project, user)
    # Leaving does not require publication/current NDA: withdrawing a
    # collaborator membership must remain possible in a hidden/draft project.
    membership = db.scalar(select(ProjectMember).where(ProjectMember.project_id == project_id, ProjectMember.user_id == user_id).with_for_update().execution_options(populate_existing=True))
    if not membership:
        raise HTTPException(404, "Участник команды не найден")
    if membership.member_role != "collaborator" or user_id in {project.owner_id, project.mentor_id}:
        raise HTTPException(409, "Можно удалить только отдельного участника команды")
    ongoing = db.scalar(select(Participation.id).where(Participation.project_id == project_id, Participation.mentee_id == user_id, Participation.status.in_(["active", "paused"])).limit(1))
    if ongoing:
        raise HTTPException(409, "Сначала завершите участие в менторстве через отдельный процесс")
    membership_id = membership.id
    db.delete(membership)
    db.flush()
    audit(db, user, "team.member_left" if is_self else "team.member_removed", "project_member", membership_id, {"project_id": project_id, "user_id": user_id, "reason": payload.reason})
    recipients = {user_id}
    if is_self:
        recipients.update(identifier for identifier in (project.owner_id, project.mentor_id) if identifier and identifier != actor_id)
    for recipient_id in recipients:
        db.add(Notification(user_id=recipient_id, kind="team_membership", title="Членство в команде изменено", body="Проверьте актуальное членство в разделе команды. История проекта сохранена."))
    occupied = team_occupied(db, project)
    commit(db)
    return {"project_id": project_id, "user_id": user_id, "removed": True, "self_left": is_self, "occupied": occupied}


def attachment_view(attachment):
    return {"id": attachment.id, "project_id": attachment.project_id, "uploader_id": attachment.uploader_id, "filename": attachment.filename, "content_type": attachment.content_type, "size_bytes": attachment.size_bytes, "created_at": attachment.created_at, "download_path": "/api/v1/attachments/" + attachment.id + "/download"}


@router.get("/attachment-policy")
def attachment_policy(user: User = Depends(require_active)):
    return {"max_bytes": settings.upload_max_bytes, "extensions": list(TYPES), "storage_configured": storage_ready()}


@router.get("/projects/{project_id}/attachments")
def list_attachments(project_id: str, limit: int = Query(50, ge=1, le=100), offset: int = Query(0, ge=0), user: User = Depends(require_active), db: Session = Depends(get_db)):
    get_project(db, project_id, user, private=True)
    rows = db.scalars(select(PrivateAttachment).where(PrivateAttachment.project_id == project_id, PrivateAttachment.status == "active").order_by(PrivateAttachment.created_at.desc()).limit(limit).offset(offset)).all()
    return [attachment_view(row) for row in rows]


@router.post("/projects/{project_id}/attachments", status_code=201)
def upload_attachment(project_id: str, file: UploadFile = File(...), user: User = Depends(require_active), db: Session = Depends(get_db)):
    user = lock_users(db, [user.id])[user.id]
    project = lock_project(db, project_id)
    private_permission(db, project, user)
    count = db.scalar(select(func.count(PrivateAttachment.id)).where(PrivateAttachment.project_id == project.id, PrivateAttachment.status == "active"))
    total = db.scalar(select(func.sum(PrivateAttachment.size_bytes)).where(PrivateAttachment.project_id == project.id, PrivateAttachment.status == "active")) or 0
    if count >= 100 or total >= 100 * 1024 * 1024:
        raise HTTPException(409, "Достигнут лимит файлов проекта")
    data = file.file.read(settings.upload_max_bytes + 1)
    try:
        filename, content_type, digest = inspect_attachment(file.filename, file.content_type or "application/octet-stream", data)
    except InvalidAttachment as exc:
        raise HTTPException(422, str(exc)) from None
    if total + len(data) > 100 * 1024 * 1024:
        raise HTTPException(409, "Общий размер файлов проекта превышает 100 МБ")
    try:
        provider, key = put_private(data, content_type)
    except StorageUnavailable:
        raise HTTPException(503, "Закрытое хранилище недоступно") from None
    attachment = PrivateAttachment(project_id=project.id, uploader_id=user.id, filename=filename, content_type=content_type, size_bytes=len(data), sha256=digest, storage_provider=provider, storage_key=key)
    try:
        db.add(attachment)
        db.flush()
        audit(db, user, "attachment.uploaded", "private_attachment", attachment.id, {"size_bytes": len(data)})
        commit(db)
    except Exception:
        try:
            delete_private(provider, key)
        except StorageUnavailable:
            pass
        raise
    return attachment_view(attachment)


@router.get("/attachments/{attachment_id}/download")
def download_attachment(attachment_id: str, user: User = Depends(require_active), db: Session = Depends(get_db)):
    attachment = db.get(PrivateAttachment, attachment_id)
    if not attachment or attachment.status != "active":
        raise HTTPException(404, "Файл не найден")
    get_project(db, attachment.project_id, user, private=True)
    try:
        data = read_private(attachment.storage_provider, attachment.storage_key, attachment.size_bytes)
    except StorageUnavailable:
        raise HTTPException(503, "Файл временно недоступен") from None
    if hashlib.sha256(data).hexdigest() != attachment.sha256:
        raise HTTPException(503, "Не удалось подтвердить целостность файла")
    audit(db, user, "attachment.downloaded", "private_attachment", attachment.id)
    commit(db)
    return Response(data, media_type=attachment.content_type, headers={"Content-Disposition": download_disposition(attachment.filename), "Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff", "Content-Security-Policy": "sandbox"})


@router.delete("/attachments/{attachment_id}")
def remove_attachment(attachment_id: str, user: User = Depends(require_active), db: Session = Depends(get_db)):
    attachment = db.get(PrivateAttachment, attachment_id)
    if not attachment or attachment.status != "active":
        raise HTTPException(404, "Файл не найден")
    project = get_project(db, attachment.project_id, user, private=True)
    if user.id not in {attachment.uploader_id, project.owner_id} and user.role != "admin":
        raise HTTPException(404, "Файл не найден")
    try:
        delete_private(attachment.storage_provider, attachment.storage_key)
    except StorageUnavailable:
        raise HTTPException(503, "Не удалось удалить файл из хранилища") from None
    attachment.status, attachment.deleted_at = "deleted", utcnow()
    audit(db, user, "attachment.deleted", "private_attachment", attachment.id)
    commit(db)
    return {"id": attachment.id, "status": attachment.status}
