"""Projects, guarded matching transactions, and membership-scoped messages."""
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth import get_current_user, has_current_consents, require_active, require_admin
from app.database import get_db
from app.models import Application, AuditEvent, Consent, Conversation, ConversationMember, Direction, Document, DocumentVersion, Message, Notification, Participation, ParticipationEvent, Project, ProjectMember, User
from app.schemas.projects import ApplicationCreate, ApplicationDecision, MessageCreate, ProjectCreate, ProjectReview, ProjectUpdate


router = APIRouter()
ONGOING = ("active", "paused")


def audit(db, user, action, entity_type, entity_id, detail=None):
    db.add(AuditEvent(actor_id=user.id, action=action, entity_type=entity_type, entity_id=entity_id, detail=detail or {}))


def notify(db, user_id, kind, title, body=""):
    db.add(Notification(user_id=user_id, kind=kind, title=title, body=body))


def commit(db):
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Такая заявка или активное участие уже существует. Обновите страницу")


def public_project(db, project):
    # Explicit whitelist: never return the ORM __dict__ or private_details.
    owner = db.get(User, project.owner_id)
    mentor = db.get(User, project.mentor_id) if project.mentor_id else None
    direction = db.get(Direction, project.direction_id)
    from app.project_capacity import project_occupied
    occupied = project_occupied(db, project)
    return {"id": project.id, "owner_id": project.owner_id, "owner_name": owner.full_name if owner else "", "owner_role": owner.role if owner else "", "mentor_id": project.mentor_id, "mentor_name": mentor.full_name if mentor else None, "direction_id": project.direction_id, "direction_name": direction.name_ru if direction else "", "title": project.title, "problem": project.problem, "description": project.description, "stage": project.stage, "required_skills": project.required_skills or [], "capacity": project.capacity, "occupied": occupied, "available_places": max(0, project.capacity - occupied), "visibility_status": project.visibility_status, "created_at": project.created_at}


def application_dict(db, application):
    mentor, mentee = db.get(User, application.mentor_id), db.get(User, application.mentee_id)
    project = db.get(Project, application.project_id) if application.project_id else None
    conversation_id = db.scalar(select(Conversation.id).where(Conversation.application_id == application.id))
    return {"id": application.id, "project_id": application.project_id, "mentee_id": application.mentee_id, "mentor_id": application.mentor_id, "motivation": application.motivation, "status": application.status, "rejection_reason": application.rejection_reason, "created_at": application.created_at, "mentor_name": mentor.full_name if mentor else "", "mentee_name": mentee.full_name if mentee else "", "project_title": project.title if project else None, "conversation_id": conversation_id}


def participant_dict(db, participation):
    mentee = db.get(User, participation.mentee_id)
    mentor = db.get(User, participation.mentor_id) if participation.mentor_id else None
    project = db.get(Project, participation.project_id) if participation.project_id else None
    return {"id": participation.id, "project_id": participation.project_id, "mentee_id": participation.mentee_id, "mentor_id": participation.mentor_id, "status": participation.status, "started_at": participation.started_at, "completed_at": participation.completed_at, "project_title": project.title if project else None, "mentee_name": mentee.full_name if mentee else "", "mentor_name": mentor.full_name if mentor else None}


def project_member(db, project, user):
    if user.id in {project.owner_id, project.mentor_id}:
        return True
    return db.scalar(select(ProjectMember.id).where(ProjectMember.project_id == project.id, ProjectMember.user_id == user.id)) is not None


def project_direction(db, direction_id):
    direction = db.get(Direction, direction_id)
    if not direction or not direction.active:
        raise HTTPException(422, "Выберите действующее направление")
    return direction


def ensure_user_enrolled(db, user, role):
    if user.role != role or user.account_status != "active" or not user.profile_completed:
        raise HTTPException(403, "Участник должен иметь одобренную анкету и подходящую роль")
    if role == "mentor" and not user.intake_open:
        raise HTTPException(409, "Набор участника сейчас закрыт")
    if not has_current_consents(db, user):
        raise HTTPException(409, "Участник должен подтвердить актуальные обязательные документы")


def lock_mentor(db, mentor_id):
    """Writes acquire SQLite's writer lock; FOR UPDATE supplies PostgreSQL row lock.

    Capacity counts occur only AFTER these locks, inside the same transaction.
    The no-op write is intentional: SELECT FOR UPDATE has no effect in SQLite.
    """
    if db.get_bind().dialect.name != "sqlite":
        db.scalar(select(User).where(User.id == mentor_id).with_for_update())
    acquired = db.execute(update(User).where(User.id == mentor_id, User.role == "mentor", User.account_status == "active", User.profile_completed.is_(True), User.intake_open.is_(True), User.capacity > 0).values(capacity=User.capacity).execution_options(synchronize_session=False))
    if acquired.rowcount != 1:
        db.rollback()
        raise HTTPException(409, "Ментор недоступен для новых участников")
    mentor = db.get(User, mentor_id)
    db.refresh(mentor)
    ensure_user_enrolled(db, mentor, "mentor")
    occupied = db.scalar(select(func.count(Participation.id)).where(Participation.mentor_id == mentor.id, Participation.status.in_(ONGOING))) or 0
    if occupied >= mentor.capacity:
        db.rollback()
        raise HTTPException(409, "У ментора нет свободных мест")
    return mentor


def lock_project(db, project_id, incoming_user_id=None):
    if db.get_bind().dialect.name != "sqlite":
        db.scalar(select(Project).where(Project.id == project_id).with_for_update())
    acquired = db.execute(update(Project).where(Project.id == project_id, Project.visibility_status == "published").values(capacity=Project.capacity).execution_options(synchronize_session=False))
    if acquired.rowcount != 1:
        db.rollback()
        raise HTTPException(409, "Проект недоступен для новых участников")
    project = db.get(Project, project_id)
    db.refresh(project)
    from app.project_capacity import project_occupant_ids
    occupants = project_occupant_ids(db, project)
    if len(occupants) >= project.capacity and incoming_user_id not in occupants:
        db.rollback()
        raise HTTPException(409, "В проекте нет свободных мест")
    project_direction(db, project.direction_id)
    return project


def validate_match(db, project, mentee, mentor):
    if project is None:
        if not set(mentee.direction_ids or []) & set(mentor.direction_ids or []):
            raise HTTPException(409, "У участников нет общего направления")
        return
    if project.direction_id not in (mentee.direction_ids or []) or project.direction_id not in (mentor.direction_ids or []):
        raise HTTPException(409, "Направление проекта должно быть в анкетах участников")
    if project.mentor_id and project.mentor_id != mentor.id:
        raise HTTPException(409, "В проекте уже назначен другой ментор")
    if project.mentor_id is None and project.owner_id != mentee.id:
        raise HTTPException(403, "Сначала автор проекта должен согласовать ментора")


@router.get("/projects")
def projects(direction_id: str | None = None, stage: str | None = None, q: str | None = Query(None, max_length=200), limit: int = Query(50, ge=1, le=100), offset: int = Query(0, ge=0), db: Session = Depends(get_db)):
    query = select(Project).join(Direction, Direction.id == Project.direction_id).join(User, User.id == Project.owner_id).where(Project.visibility_status == "published", Direction.active.is_(True), User.account_status == "active")
    if direction_id:
        query = query.where(Project.direction_id == direction_id)
    if stage:
        query = query.where(Project.stage == stage)
    if q:
        query = query.where(or_(Project.title.icontains(q, autoescape=True), Project.problem.icontains(q, autoescape=True)))
    rows = db.scalars(query.order_by(Project.created_at.desc(), Project.id).limit(limit).offset(offset)).all()
    return [public_project(db, project) for project in rows]


@router.get("/projects/mine")
def own_projects(limit: int = Query(50, ge=1, le=100), offset: int = Query(0, ge=0), user: User = Depends(require_active), db: Session = Depends(get_db)):
    memberships = select(ProjectMember.project_id).where(ProjectMember.user_id == user.id)
    rows = db.scalars(select(Project).where(or_(Project.owner_id == user.id, Project.mentor_id == user.id, Project.id.in_(memberships))).order_by(Project.created_at.desc(), Project.id).limit(limit).offset(offset)).all()
    return [public_project(db, project) for project in rows]


@router.post("/projects", status_code=201)
def create_project(payload: ProjectCreate, user: User = Depends(require_active), db: Session = Depends(get_db)):
    from app.transactions import lock_users
    user_id = user.id
    user = lock_users(db, [user_id])[user_id]
    if user.role not in {"mentor", "mentee"}:
        raise HTTPException(403, "Проект может создать ментор или менти")
    ensure_user_enrolled(db, user, user.role)
    project_direction(db, payload.direction_id)
    if payload.direction_id not in (user.direction_ids or []):
        raise HTTPException(422, "Добавьте направление проекта в свою анкету")
    project = Project(**payload.model_dump(), owner_id=user.id, mentor_id=user.id if user.role == "mentor" else None, visibility_status="pending")
    db.add(project)
    db.flush()
    db.add(ProjectMember(project_id=project.id, user_id=user.id, member_role="owner"))
    audit(db, user, "project.created", "project", project.id)
    for admin_id in db.scalars(select(User.id).where(User.role == "admin", User.account_status == "active")):
        notify(db, admin_id, "project_review", "Новый проект ожидает модерации", project.title)
    commit(db)
    return public_project(db, project)


@router.get("/projects/{project_id}")
def project_detail(project_id: str, request: Request, db: Session = Depends(get_db)):
    project = db.get(Project, project_id)
    if not project:
        raise HTTPException(404, "Проект не найден")
    direction = db.get(Direction, project.direction_id)
    owner = db.get(User, project.owner_id)
    public = project.visibility_status == "published" and direction and direction.active and owner and owner.account_status == "active"
    if not public:
        if not request.cookies.get("dc_session"):
            raise HTTPException(404, "Проект не найден")
        user = get_current_user(request, db)
        if user.role != "admin" and not project_member(db, project, user):
            raise HTTPException(404, "Проект не найден")
    return public_project(db, project)


@router.get("/projects/{project_id}/access")
def project_access(project_id: str, user: User = Depends(require_active), db: Session = Depends(get_db)):
    project = db.get(Project, project_id)
    if not project:
        raise HTTPException(404, "Проект не найден")
    is_member = user.role == "admin" or project_member(db, project, user)
    if project.visibility_status != "published" and not is_member:
        raise HTTPException(404, "Проект не найден")
    return {"is_member": is_member, "can_invite": user.role == "admin" or user.id in {project.owner_id, project.mentor_id}}


@router.patch("/projects/{project_id}")
def edit_project(project_id: str, payload: ProjectUpdate, user: User = Depends(require_active), db: Session = Depends(get_db)):
    from app.transactions import lock_users
    user_id = user.id
    user = lock_users(db, [user_id])[user_id]
    if user.role not in {"mentor", "mentee"} or user.account_status != "active" or not user.profile_completed or not has_current_consents(db, user):
        raise HTTPException(403, "Для редактирования нужны одобренная анкета и актуальные согласия")
    # Guarded write obtains serialization before checking current membership/capacity.
    changed = db.execute(update(Project).where(Project.id == project_id, Project.owner_id == user.id).values(capacity=Project.capacity).execution_options(synchronize_session=False))
    if changed.rowcount != 1:
        db.rollback()
        raise HTTPException(404, "Свой проект не найден")
    project = db.get(Project, project_id)
    db.refresh(project)
    data = payload.model_dump(exclude_unset=True)
    if "direction_id" in data:
        project_direction(db, data["direction_id"])
        if data["direction_id"] not in (user.direction_ids or []):
            raise HTTPException(422, "Направление должно быть в вашей анкете")
        if data["direction_id"] != project.direction_id and db.scalar(select(Participation.id).where(Participation.project_id == project.id).limit(1)):
            raise HTTPException(409, "Направление проекта с участниками изменить нельзя")
    if "capacity" in data:
        from app.project_capacity import project_occupied
        occupied = project_occupied(db, project)
        if data["capacity"] < occupied:
            raise HTTPException(409, "Лимит не может быть меньше числа текущих участников")
    for key, value in data.items():
        setattr(project, key, value)
    project.visibility_status = "pending"
    audit(db, user, "project.edited", "project", project.id, {"fields": list(data), "requires_review": True})
    commit(db)
    return public_project(db, project)


@router.get("/projects/{project_id}/private")
def private_project(project_id: str, user: User = Depends(require_active), db: Session = Depends(get_db)):
    project = db.get(Project, project_id)
    if project is None or not project_member(db, project, user):
        raise HTTPException(404, "Проект не найден или нет доступа к закрытым материалам")
    if user.role == "mentor":
        documents = db.scalars(select(Document).where(Document.active.is_(True), Document.scope == "private_project")).all()
        accepted = set(db.scalars(select(Consent.document_version_id).where(Consent.user_id == user.id)).all())
        applicable = False
        for document in documents:
            if document.required_roles and user.role not in document.required_roles:
                continue
            if document.direction_id and document.direction_id != project.direction_id:
                continue
            applicable = True
            version = db.scalar(select(DocumentVersion).where(DocumentVersion.document_id == document.id).order_by(DocumentVersion.published_at.desc(), DocumentVersion.id.desc()).limit(1))
            if version is None or version.id not in accepted:
                raise HTTPException(403, "Подтвердите актуальный NDA для закрытых материалов проекта")
        if not applicable:
            raise HTTPException(403, "Для проекта ещё не опубликован актуальный NDA")
    audit(db, user, "project.private_viewed", "project", project.id)
    commit(db)
    return {"id": project.id, "private_details": project.private_details}


@router.get("/admin/projects")
def admin_projects(status: str | None = None, limit: int = Query(50, ge=1, le=100), offset: int = Query(0, ge=0), user: User = Depends(require_admin), db: Session = Depends(get_db)):
    query = select(Project)
    if status:
        query = query.where(Project.visibility_status == status)
    return [public_project(db, project) for project in db.scalars(query.order_by(Project.created_at.desc(), Project.id).limit(limit).offset(offset)).all()]


@router.post("/admin/projects/{project_id}/review")
def review_project(project_id: str, payload: ProjectReview, user: User = Depends(require_admin), db: Session = Depends(get_db)):
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(404, "Проект не найден")
    from app.transactions import lock_users
    owner = lock_users(db, [project.owner_id, user.id])[project.owner_id]
    project = db.scalar(select(Project).where(Project.id == project_id).with_for_update())
    if project is None:
        raise HTTPException(404, "Проект не найден")
    project_direction(db, project.direction_id)
    if payload.decision == "published" and (owner.account_status != "active" or not owner.profile_completed or not has_current_consents(db, owner)):
        raise HTTPException(409, "Перед публикацией автору нужны одобренная анкета и актуальные согласия")
    project.visibility_status = payload.decision
    audit(db, user, "project.reviewed", "project", project.id, {"decision": payload.decision, "reason": payload.reason})
    notify(db, project.owner_id, "project_review", "Проект опубликован" if payload.decision == "published" else "Проект скрыт", payload.reason)
    commit(db)
    return public_project(db, project)


@router.get("/applications")
def applications(limit: int = Query(50, ge=1, le=100), offset: int = Query(0, ge=0), user: User = Depends(require_active), db: Session = Depends(get_db)):
    rows = db.scalars(select(Application).where(or_(Application.mentee_id == user.id, Application.mentor_id == user.id)).order_by(Application.created_at.desc(), Application.id).limit(limit).offset(offset)).all()
    return [application_dict(db, application) for application in rows]


@router.post("/applications", status_code=201)
def create_application(payload: ApplicationCreate, user: User = Depends(require_active), db: Session = Depends(get_db)):
    from app.transactions import lock_users
    user_id = user.id
    people = lock_users(db, [user_id, payload.mentor_id])
    user = people[user_id]
    ensure_user_enrolled(db, user, "mentee")
    if user.id == payload.mentor_id:
        raise HTTPException(422, "Нельзя подать заявку самому себе")
    mentor = lock_mentor(db, payload.mentor_id)
    project = lock_project(db, payload.project_id, user.id) if payload.project_id else None
    validate_match(db, project, user, mentor)
    duplicate = select(Participation.id).where(Participation.mentee_id == user.id, Participation.status.in_(ONGOING))
    duplicate = duplicate.where(Participation.project_id == project.id) if project else duplicate.where(Participation.project_id.is_(None), Participation.mentor_id == mentor.id)
    if db.scalar(duplicate.limit(1)):
        db.rollback()
        raise HTTPException(409, "Активное участие уже существует")
    application = Application(**payload.model_dump(), mentee_id=user.id, status="pending")
    db.add(application)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Заявка уже ожидает решения")
    notify(db, mentor.id, "application", "Новая заявка на менторство", f"От {user.full_name}")
    audit(db, user, "application.created", "application", application.id)
    commit(db)
    return application_dict(db, application)


@router.post("/applications/{application_id}/decision")
def decide_application(application_id: str, payload: ApplicationDecision, user: User = Depends(require_active), db: Session = Depends(get_db)):
    application = db.get(Application, application_id)
    if application is None or application.mentor_id != user.id or user.role != "mentor":
        raise HTTPException(404, "Входящая заявка не найдена")
    from app.transactions import lock_users
    actor_id, mentee_id = user.id, application.mentee_id
    people = lock_users(db, [actor_id, mentee_id])
    user = people[actor_id]
    application = db.get(Application, application_id, populate_existing=True)
    if user.role != "mentor" or user.account_status != "active" or not user.profile_completed or not has_current_consents(db, user):
        raise HTTPException(403, "Ментор должен иметь одобренную анкету и актуальные согласия")
    if application is None or application.mentor_id != user.id or application.mentee_id != mentee_id:
        raise HTTPException(404, "Входящая заявка не найдена")
    if payload.decision == "rejected":
        changed = db.execute(update(Application).where(Application.id == application_id, Application.mentor_id == user.id, Application.status == "pending").values(status="rejected", rejection_reason=payload.reason))
        if changed.rowcount != 1:
            db.rollback()
            raise HTTPException(409, "По заявке уже принято решение")
        notify(db, application.mentee_id, "application_decision", "Заявка отклонена", payload.reason)
        audit(db, user, "application.rejected", "application", application.id, {"reason": payload.reason})
        commit(db)
        return application_dict(db, application)
    mentor = lock_mentor(db, user.id)
    project = lock_project(db, application.project_id, application.mentee_id) if application.project_id else None
    # A stale object from dependency reads must not bypass a concurrent withdrawal.
    db.refresh(application)
    if application.status != "pending":
        db.rollback()
        raise HTTPException(409, "По заявке уже принято решение")
    mentee = db.get(User, application.mentee_id)
    db.refresh(mentee)
    ensure_user_enrolled(db, mentee, "mentee")
    validate_match(db, project, mentee, mentor)
    changed = db.execute(update(Application).where(Application.id == application.id, Application.status == "pending").values(status="accepted"))
    if changed.rowcount != 1:
        db.rollback()
        raise HTTPException(409, "По заявке уже принято решение")
    if project and project.mentor_id is None:
        project.mentor_id = mentor.id
    participation = Participation(project_id=application.project_id, mentee_id=mentee.id, mentor_id=mentor.id, status="active")
    db.add(participation)
    try:
        db.flush()
        db.add(ParticipationEvent(participation_id=participation.id, actor_id=user.id, from_status=None, to_status="active", reason="application_accepted"))
        if project:
            for member_id, role in ((mentee.id, "mentee"), (mentor.id, "mentor")):
                exists = db.scalar(select(ProjectMember.id).where(ProjectMember.project_id == project.id, ProjectMember.user_id == member_id))
                if not exists:
                    db.add(ProjectMember(project_id=project.id, user_id=member_id, member_role=role))
        conversation = Conversation(application_id=application.id, participation_id=participation.id)
        db.add(conversation)
        db.flush()
        db.add_all([ConversationMember(conversation_id=conversation.id, user_id=mentee.id), ConversationMember(conversation_id=conversation.id, user_id=mentor.id)])
        notify(db, mentee.id, "application_decision", "Ментор принял заявку", "Участие создано. Можно обсудить встречу в сообщениях")
        notify(db, mentor.id, "participation", "Новое участие создано", mentee.full_name)
        audit(db, user, "application.accepted", "application", application.id, {"participation_id": participation.id, "conversation_id": conversation.id})
        commit(db)
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Активное участие уже существует")
    response = application_dict(db, application)
    response["participation_id"] = participation.id
    return response


@router.post("/applications/{application_id}/withdraw")
def withdraw_application(application_id: str, user: User = Depends(require_active), db: Session = Depends(get_db)):
    changed = db.execute(update(Application).where(Application.id == application_id, Application.mentee_id == user.id, Application.status == "pending").values(status="withdrawn"))
    if changed.rowcount != 1:
        db.rollback()
        raise HTTPException(409, "Можно отозвать только собственную заявку, ожидающую решения")
    application = db.get(Application, application_id)
    notify(db, application.mentor_id, "application_withdrawn", "Заявка отозвана")
    audit(db, user, "application.withdrawn", "application", application_id)
    commit(db)
    return application_dict(db, application)


@router.get("/participations")
def participations(limit: int = Query(50, ge=1, le=100), offset: int = Query(0, ge=0), user: User = Depends(require_active), db: Session = Depends(get_db)):
    rows = db.scalars(select(Participation).where(or_(Participation.mentee_id == user.id, Participation.mentor_id == user.id)).order_by(Participation.started_at.desc(), Participation.id).limit(limit).offset(offset)).all()
    return [participant_dict(db, row) for row in rows]


@router.get("/admin/participations")
def administrative_participations(status: str | None = Query(None, pattern=r"^(active|paused|completed_successfully|completed_early)$"),
    limit: int = Query(50, ge=1, le=100), offset: int = Query(0, ge=0),
    user: User = Depends(require_admin), db: Session = Depends(get_db)):
    query = select(Participation)
    if status:
        query = query.where(Participation.status == status)
    return [participant_dict(db, row) for row in db.scalars(query.order_by(Participation.started_at.desc(), Participation.id).limit(limit).offset(offset)).all()]


def conversation_member(db, conversation_id, user):
    conversation = db.get(Conversation, conversation_id)
    member = db.scalar(select(ConversationMember.id).where(ConversationMember.conversation_id == conversation_id, ConversationMember.user_id == user.id))
    if not conversation or not member:
        raise HTTPException(404, "Диалог не найден")
    return conversation


@router.get("/conversations")
def conversations(limit: int = Query(50, ge=1, le=100), offset: int = Query(0, ge=0), user: User = Depends(require_active), db: Session = Depends(get_db)):
    rows = db.scalars(select(Conversation).join(ConversationMember, ConversationMember.conversation_id == Conversation.id).where(ConversationMember.user_id == user.id).order_by(Conversation.created_at.desc(), Conversation.id).limit(limit).offset(offset)).all()
    output = []
    for conversation in rows:
        members = db.scalars(select(User).join(ConversationMember, ConversationMember.user_id == User.id).where(ConversationMember.conversation_id == conversation.id, User.id != user.id)).all()
        participation = db.get(Participation, conversation.participation_id) if conversation.participation_id else None
        project = db.get(Project, participation.project_id) if participation and participation.project_id else None
        output.append({"id": conversation.id, "application_id": conversation.application_id, "participation_id": conversation.participation_id, "title": project.title if project else "Менторство", "other_name": ", ".join(member.full_name for member in members), "created_at": conversation.created_at})
    return output


def message_dict(db, message):
    sender = db.get(User, message.sender_id)
    return {"id": message.id, "conversation_id": message.conversation_id, "sender_id": message.sender_id, "sender_name": sender.full_name if sender else "", "body": message.body, "created_at": message.created_at}


@router.get("/conversations/{conversation_id}/messages")
def messages(conversation_id: str, limit: int = Query(50, ge=1, le=100), offset: int = Query(0, ge=0), user: User = Depends(require_active), db: Session = Depends(get_db)):
    conversation_member(db, conversation_id, user)
    # offset=0 is the latest window, returned chronologically for the chat UI.
    rows = db.scalars(select(Message).where(Message.conversation_id == conversation_id).order_by(Message.created_at.desc(), Message.id.desc()).limit(limit).offset(offset)).all()
    return [message_dict(db, message) for message in reversed(rows)]


@router.post("/conversations/{conversation_id}/messages", status_code=201)
def send_message(conversation_id: str, payload: MessageCreate, user: User = Depends(require_active), db: Session = Depends(get_db)):
    from app.services.action_limits import enforce_action_limit
    from app.transactions import lock_users
    actor_id = user.id
    user = lock_users(db, [actor_id])[actor_id]
    require_active(user, db)
    conversation_member(db, conversation_id, user)
    enforce_action_limit(db, actor_id, "message.sent")
    message = Message(conversation_id=conversation_id, sender_id=user.id, body=payload.body)
    db.add(message)
    db.flush()
    audit(db, user, "message.sent", "message", message.id)
    for member_id in db.scalars(select(ConversationMember.user_id).where(ConversationMember.conversation_id == conversation_id, ConversationMember.user_id != user.id)):
        # Store a generic notification; private message content stays in its dialog.
        notify(db, member_id, "message", "Новое сообщение", user.full_name)
    commit(db)
    return message_dict(db, message)
