"""Atomic participation exits, optional feedback and consent-gated public cases."""
import csv
import io

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session

from app.auth import get_current_user, has_current_consents, require_active, require_admin
from app.config import settings
from app.profile_state import admitted_profile
from app.database import get_db
from app.models import (AuditEvent, Booking, Feedback, Notification, Participation,
                        ParticipationEvent, Project, ProjectMember, Result,
                        ShowcaseConsent, Slot, User, utcnow)
from app.schemas.results import CompleteInput, FeedbackInput, PauseInput, ShowcaseConsentInput
from app.transactions import lock_users

router = APIRouter(tags=["results"])
EXIT_REASONS = [
    {"value": "goal_achieved", "label": "Цель достигнута"},
    {"value": "lack_time", "label": "Недостаточно времени"},
    {"value": "changed_interests", "label": "Изменились интересы"},
    {"value": "mentorship_mismatch", "label": "Не подошёл формат менторства"},
    {"value": "technical_issue", "label": "Технические трудности"},
    {"value": "personal_circumstances", "label": "Личные обстоятельства"},
    {"value": "other", "label": "Другая причина"},
]
CLOSED = ("completed_successfully", "completed_early")


def _demo_mode(db):
    # A persisted synthetic dataset must stay labelled after a settings toggle.
    return bool(settings.demo_mode or db.scalar(select(AuditEvent.id).where(AuditEvent.action == "demo_seed").limit(1)))


def _commit(db):
    try:
        db.commit()
    except (IntegrityError, OperationalError):
        db.rollback()
        raise HTTPException(409, "Данные изменились. Обновите страницу и повторите действие")


def _active(db, person):
    if person.account_status != "active" or (person.role != "admin" and not admitted_profile(person)):
        raise HTTPException(403, "Участник не допущен к работе на платформе")
    if not has_current_consents(db, person):
        raise HTTPException(403, "Подтвердите актуальные обязательные документы")


def _party(db, participation_id, actor_id, *, locked=True):
    row = db.get(Participation, participation_id)
    if not row:
        raise HTTPException(404, "Участие не найдено")
    ids = [actor_id, row.mentee_id] + ([row.mentor_id] if row.mentor_id else [])
    people = lock_users(db, ids) if locked else {identifier: db.get(User, identifier) for identifier in ids}
    actor = people[actor_id]
    _active(db, actor)
    row = db.get(Participation, participation_id, populate_existing=True)
    authorized = (actor.role == "admin" or
                  (row.mentee_id == actor_id and actor.role == "mentee") or
                  (row.mentor_id == actor_id and actor.role == "mentor"))
    if not authorized:
        raise HTTPException(404, "Участие не найдено")
    return row, actor, people


def _event(db, row, actor, next_status, reason):
    db.add(ParticipationEvent(participation_id=row.id, actor_id=actor.id,
                             from_status=row.status, to_status=next_status, reason=reason))
    db.add(AuditEvent(actor_id=actor.id, action="participation." + next_status,
                      entity_type="participation", entity_id=row.id,
                      detail={"from_status": row.status, "to_status": next_status}))
    row.status = next_status


def _cancel_future_bookings(db, row):
    """Same ordered user locks as booking mutations protect this transaction."""
    bookings = db.scalars(select(Booking).join(Slot, Slot.id == Booking.slot_id).where(
        Booking.participation_id == row.id, Booking.status == "scheduled", Slot.starts_at > utcnow()))
    count = 0
    for booking in bookings:
        from app.booking_lifecycle import cancel_reservation
        cancel_reservation(db, booking)
        count += 1
    return count


def _notify(db, row, title, body):
    for identifier in {row.mentee_id, row.mentor_id} - {None}:
        db.add(Notification(user_id=identifier, kind="participation", title=title, body=body))


def _feedback_view(item):
    return {"id": item.id, "author_id": item.author_id, "target_role": item.target_role,
            "rating": item.rating, "nps": item.nps, "comment": item.comment, "created_at": item.created_at}


def _result_view(db, item):
    participation = db.get(Participation, item.participation_id)
    project = db.get(Project, participation.project_id) if participation.project_id else None
    mentee = db.get(User, participation.mentee_id)
    mentor = db.get(User, participation.mentor_id) if participation.mentor_id else None
    feedback = db.scalars(select(Feedback).where(Feedback.participation_id == participation.id)
                         .order_by(Feedback.created_at, Feedback.id)).all()
    return {"id": item.id, "participation_id": item.participation_id,
            "project_id": project.id if project else None, "project_title": project.title if project else None,
            "mentee_name": mentee.full_name, "mentor_name": mentor.full_name if mentor else None,
            "status": item.status, "exit_reason": item.exit_reason, "initiator": item.initiator,
            "artifact_url": item.artifact_url, "summary": item.summary, "meeting_count": item.meeting_count,
            "verification_status": item.verification_status, "completed_at": item.completed_at,
            "feedback": [_feedback_view(entry) for entry in feedback]}


@router.get("/exit-reasons")
def exit_reasons():
    return EXIT_REASONS


@router.post("/participations/{participation_id}/pause")
def pause(participation_id: str, payload: PauseInput, user: User = Depends(require_active), db: Session = Depends(get_db)):
    row, actor, _ = _party(db, participation_id, user.id)
    if row.status == "paused":
        return {"id": row.id, "status": row.status}
    if row.status != "active":
        raise HTTPException(409, "Завершённое участие нельзя поставить на паузу")
    cancelled = _cancel_future_bookings(db, row)
    _event(db, row, actor, "paused", payload.reason)
    _notify(db, row, "Участие на паузе", f"Будущие встречи отменены: {cancelled}. Новые записи доступны после возобновления.")
    _commit(db)
    return {"id": row.id, "status": row.status, "cancelled_bookings": cancelled}


@router.post("/participations/{participation_id}/resume")
def resume(participation_id: str, user: User = Depends(require_active), db: Session = Depends(get_db)):
    row, actor, people = _party(db, participation_id, user.id)
    for identifier, role in [(row.mentee_id, "mentee"), (row.mentor_id, "mentor")]:
        if identifier:
            _active(db, people[identifier])
            if people[identifier].role != role:
                raise HTTPException(409, "Роль участника изменилась. Обратитесь к администратору")
    if row.status == "active":
        return {"id": row.id, "status": row.status}
    if row.status != "paused":
        raise HTTPException(409, "Завершённое участие нельзя возобновить")
    _event(db, row, actor, "active", "Возобновление участия")
    _notify(db, row, "Участие возобновлено", "Можно снова планировать встречи.")
    _commit(db)
    return {"id": row.id, "status": row.status}


@router.post("/participations/{participation_id}/complete")
def complete(participation_id: str, payload: CompleteInput, user: User = Depends(require_active), db: Session = Depends(get_db)):
    row, actor, _ = _party(db, participation_id, user.id)
    existing = db.scalar(select(Result).where(Result.participation_id == row.id))
    if existing:
        return _result_view(db, existing)
    if row.status in CLOSED:
        raise HTTPException(409, "Участие уже завершено. Обратитесь к администратору для проверки записи результата")
    meeting_count = db.scalar(select(func.count()).select_from(Booking).join(Slot, Slot.id == Booking.slot_id).where(
        Booking.participation_id == row.id, Booking.mentee_id == row.mentee_id,
        Booking.mentor_id == row.mentor_id, Slot.mentor_id == row.mentor_id,
        Booking.status == "completed", Slot.starts_at <= utcnow())) or 0
    cancelled = _cancel_future_bookings(db, row)
    _event(db, row, actor, payload.status, payload.exit_reason)
    row.completed_at = utcnow()
    result = Result(participation_id=row.id, status=payload.status, exit_reason=payload.exit_reason,
                    initiator=actor.role, artifact_url=payload.artifact_url, summary=payload.summary,
                    meeting_count=meeting_count, verification_status="pending", completed_at=row.completed_at)
    db.add(result)
    _notify(db, row, "Участие завершено", f"Результат сохранён и ожидает проверки. Будущие встречи отменены: {cancelled}.")
    _commit(db)
    return _result_view(db, result)


@router.get("/results")
def list_results(limit: int = Query(100, ge=1, le=200), offset: int = Query(0, ge=0),
                 user: User = Depends(require_active), db: Session = Depends(get_db)):
    query = select(Result).join(Participation, Participation.id == Result.participation_id)
    if user.role != "admin":
        if user.role == "mentee":
            query = query.where(Participation.mentee_id == user.id)
        elif user.role == "mentor":
            query = query.where(Participation.mentor_id == user.id)
        else:
            raise HTTPException(403, "Недоступно для вашей роли")
    return [_result_view(db, item) for item in db.scalars(query.order_by(Result.completed_at.desc(), Result.id)
                                                        .offset(offset).limit(limit)).all()]


@router.post("/participations/{participation_id}/feedback", status_code=201)
def leave_feedback(participation_id: str, payload: FeedbackInput, user: User = Depends(require_active), db: Session = Depends(get_db)):
    row, actor, _ = _party(db, participation_id, user.id)
    if actor.role == "admin" or not row.mentor_id:
        raise HTTPException(403, "Отзыв оставляют только стороны менторской пары")
    if row.status not in CLOSED or not db.scalar(select(Result.id).where(Result.participation_id == row.id)):
        raise HTTPException(409, "Оставьте отзыв после завершения участия")
    if db.scalar(select(Feedback.id).where(Feedback.participation_id == row.id, Feedback.author_id == actor.id)):
        raise HTTPException(409, "Ваш отзыв уже сохранён")
    feedback = Feedback(participation_id=row.id, author_id=actor.id,
                        target_role="mentor" if actor.id == row.mentee_id else "mentee",
                        rating=payload.rating, nps=payload.nps, comment=payload.comment)
    db.add(feedback)
    _commit(db)
    return _feedback_view(feedback)


def _verify(result_id, user, db, *, admin_only=False):
    result = db.get(Result, result_id)
    if not result:
        raise HTTPException(404, "Результат не найден")
    participation_id = result.participation_id
    row, actor, _ = _party(db, participation_id, user.id)
    result = db.get(Result, result_id, populate_existing=True)
    if admin_only and actor.role != "admin":
        raise HTTPException(403, "Доступ разрешён только администратору")
    if actor.role != "admin" and (actor.role != "mentor" or actor.id != row.mentor_id):
        raise HTTPException(403, "Результат подтверждает ментор пары или администратор")
    if row.status != result.status or row.status != "completed_successfully":
        raise HTTPException(409, "Подтвердить можно только успешно завершённое участие")
    try:
        CompleteInput(status=result.status, exit_reason=result.exit_reason, artifact_url=result.artifact_url, summary=result.summary)
    except ValueError:
        raise HTTPException(409, "Для проверки необходимы ссылка HTTP/HTTPS и описание результата")
    if row.project_id:
        project = db.get(Project, row.project_id)
        member = db.scalar(select(ProjectMember.id).where(ProjectMember.project_id == row.project_id,
                                                        ProjectMember.user_id == row.mentee_id))
        if not project or (project.owner_id != row.mentee_id and not member):
            raise HTTPException(409, "Результат не связан с участником выбранного проекта")
    if result.verification_status != "verified":
        result.verification_status = "verified"
        from app.services.growth import sync_user_progress
        sync_user_progress(db, row.mentee_id)
        if row.mentor_id:
            sync_user_progress(db, row.mentor_id)
        db.add(AuditEvent(actor_id=actor.id, action="result.verified", entity_type="result", entity_id=result.id,
                          detail={"participation_id": row.id}))
        _commit(db)
    return _result_view(db, result)


@router.post("/admin/results/{result_id}/verify")
def admin_verify(result_id: str, user: User = Depends(require_admin), db: Session = Depends(get_db)):
    return _verify(result_id, user, db, admin_only=True)


@router.post("/results/{result_id}/verify")
def mentor_verify(result_id: str, user: User = Depends(require_active), db: Session = Depends(get_db)):
    return _verify(result_id, user, db)


def _project_parties(db, project):
    members = set(db.scalars(select(ProjectMember.user_id).where(ProjectMember.project_id == project.id)).all())
    members.add(project.owner_id)
    if project.mentor_id:
        members.add(project.mentor_id)
    # Also protect parties in historical or direct records linked to this case.
    for row in db.scalars(select(Participation).where(Participation.project_id == project.id)).all():
        members.add(row.mentee_id)
        if row.mentor_id:
            members.add(row.mentor_id)
    return members


@router.post("/projects/{project_id}/showcase-consent")
def showcase_consent(project_id: str, payload: ShowcaseConsentInput,
                     user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    project = db.get(Project, project_id)
    if not project:
        raise HTTPException(404, "Проект не найден")
    actor_id = user.id
    actor = lock_users(db, [actor_id])[actor_id]
    project = db.get(Project, project_id, populate_existing=True)
    if actor_id not in _project_parties(db, project):
        raise HTTPException(404, "Проект не найден")
    # Revocation remains possible after profile or document requirements change.
    if payload.accepted:
        _active(db, actor)
        if actor.role not in {"mentee", "mentor"}:
            raise HTTPException(403, "Согласие дают участники проекта")
        if not has_current_consents(db, actor, scopes=("showcase",)):
            raise HTTPException(403, "Примите актуальные условия публикации кейса")
    consent = db.scalar(select(ShowcaseConsent).where(ShowcaseConsent.project_id == project_id,
                                                   ShowcaseConsent.user_id == actor_id))
    if not consent:
        consent = ShowcaseConsent(project_id=project_id, user_id=actor_id)
        db.add(consent)
    consent.accepted = payload.accepted
    consent.updated_at = utcnow()
    db.add(AuditEvent(actor_id=actor_id, action="showcase.consent", entity_type="project", entity_id=project_id,
                      detail={"accepted": payload.accepted}))
    _commit(db)
    return {"project_id": project_id, "user_id": actor_id, "accepted": consent.accepted, "updated_at": consent.updated_at}


def _showcase(db):
    output = []
    demo_mode = _demo_mode(db)
    projects = db.scalars(select(Project).where(Project.visibility_status == "published")
                          .order_by(Project.created_at.desc(), Project.id)).all()
    for project in projects:
        results = db.scalars(select(Result).join(Participation, Participation.id == Result.participation_id).where(
            Participation.project_id == project.id, Participation.status == "completed_successfully",
            Result.status == "completed_successfully", Result.verification_status == "verified")
            .order_by(Result.completed_at.desc(), Result.id)).all()
        if not results:
            continue
        parties = _project_parties(db, project)
        accepted = set(db.scalars(select(ShowcaseConsent.user_id).where(ShowcaseConsent.project_id == project.id,
                                                                      ShowcaseConsent.accepted.is_(True))).all())
        if not parties <= accepted:
            continue
        people = db.scalars(select(User).where(User.id.in_(parties)).order_by(User.id)).all()
        if len(people) != len(parties) or any(
            person.role not in {"mentee", "mentor"} or person.account_status != "active" or not admitted_profile(person)
            or not has_current_consents(db, person, scopes=("registration", "intake", "showcase")) for person in people):
            continue
        result = results[0]
        try:
            CompleteInput(status=result.status, exit_reason=result.exit_reason, artifact_url=result.artifact_url, summary=result.summary)
        except ValueError:
            continue
        output.append({"id": project.id, "title": project.title, "problem": project.problem,
                       "description": project.description, "stage": project.stage, "direction_id": project.direction_id,
                       "required_skills": project.required_skills, "result_id": result.id,
                       "artifact_url": result.artifact_url, "summary": result.summary,
                       "meeting_count": result.meeting_count, "completed_at": result.completed_at,
                       "participants": [{"name": person.full_name, "role": person.role} for person in people],
                       "demo_mode": demo_mode})
    return output


@router.get("/showcase")
def showcase(limit: int = Query(100, ge=1, le=200), offset: int = Query(0, ge=0), db: Session = Depends(get_db)):
    return _showcase(db)[offset:offset + limit]


def _analytics(db):
    people = db.scalars(select(User).where(User.account_status == "active", User.profile_completed.is_(True))).all()
    approved = {person.id for person in people if admitted_profile(person) and has_current_consents(db, person)}
    participations = db.scalars(select(Participation)).all()
    results = db.scalars(select(Result)).all()
    closed_ids = {item.participation_id for item in results}
    feedback = db.scalars(select(Feedback).where(Feedback.participation_id.in_(closed_ids))).all() if closed_ids else []
    nps_values = [entry.nps for entry in feedback if entry.nps is not None]
    nps = round(100 * (sum(value >= 9 for value in nps_values) - sum(value <= 6 for value in nps_values)) / len(nps_values), 1) if nps_values else None
    counts = {entry["value"]: 0 for entry in EXIT_REASONS}
    for item in results:
        counts[item.exit_reason] = counts.get(item.exit_reason, 0) + 1
    demo_mode = _demo_mode(db)
    data = {"demo_mode": demo_mode, "cohort": "synthetic_demo" if demo_mode else "all_records",
            "mentors": sum(person.role == "mentor" and person.id in approved for person in people),
            "mentees": sum(person.role == "mentee" and person.id in approved for person in people),
            "projects": db.scalar(select(func.count()).select_from(Project).where(Project.visibility_status == "published")) or 0,
            "completed_results": sum(item.status == "completed_successfully" for item in results),
            "verified_results": sum(item.status == "completed_successfully" and item.verification_status == "verified" for item in results),
            "completed_meetings": db.scalar(select(func.count()).select_from(Booking).where(Booking.status == "completed")) or 0,
            "showcase_projects": len(_showcase(db)),
            "active_participations": sum(item.status == "active" for item in participations),
            "paused_participations": sum(item.status == "paused" for item in participations),
            "early_results": sum(item.status == "completed_early" for item in results),
            "feedback_count": len(feedback),
            "average_rating": round(sum(entry.rating for entry in feedback) / len(feedback), 2) if feedback else None,
            "nps": nps, "nps_responses": len(nps_values),
            "exit_reasons": [{**entry, "count": counts[entry["value"]]} for entry in EXIT_REASONS],
            "definitions": {
                "cohort": "Все записи текущей базы за всё время; при demo_mode все показатели помечены как демонстрационные. Не подтверждает реальный пилот.",
                "mentors_mentees": "Активные одобренные анкеты с актуальными обязательными согласиями.",
                "projects": "Проекты со статусом published; публичная витрина требует отдельных согласий.",
                "completed_results": "Успешно завершённые участия с отдельной записью Result; одно участие считается один раз.",
                "verified_results": "Успешные результаты, отдельно подтверждённые ментором пары или администратором.",
                "completed_meetings": "Встречи со статусом completed, подтверждённые ментором; не количество созданных слотов.",
                "average_rating": "Средняя оценка по полученным отзывам завершённых пар; отсутствие отзыва не равно нулю.",
                "nps": "100 × (доля оценок 9–10 минус доля 0–6); только ответы с заполненным nps, 7–8 нейтральны.",
                "feedback_count": "Количество полученных отзывов, а не число завершённых пар. Отзывы добровольны.",
            }}
    return data


@router.get("/stats")
def public_stats(db: Session = Depends(get_db)):
    data = _analytics(db)
    fields = ("demo_mode", "cohort", "mentors", "mentees", "projects", "completed_results",
              "verified_results", "completed_meetings", "showcase_projects")
    return {field: data[field] for field in fields}


@router.get("/admin/analytics")
def admin_analytics(user: User = Depends(require_admin), db: Session = Depends(get_db)):
    return _analytics(db)


def _csv_safe(value):
    value = "" if value is None else str(value)
    if value.lstrip().startswith(("=", "+", "-", "@")) or value.startswith(("\t", "\r", "\n")):
        return "'" + value
    return value


@router.get("/admin/results/export")
def export_results(user: User = Depends(require_admin), db: Session = Depends(get_db)):
    # Structured domain fields only: no names, email, contact, comments or private project contents.
    fields = ("id", "participation_id", "status", "exit_reason", "initiator", "meeting_count", "verification_status", "completed_at")
    stream = io.StringIO(newline="")
    writer = csv.writer(stream)
    writer.writerow(["demo_mode", *fields])
    demo_mode = _demo_mode(db)
    for item in db.scalars(select(Result).order_by(Result.completed_at.desc(), Result.id)).all():
        writer.writerow([str(demo_mode).lower(), *[_csv_safe(getattr(item, field)) for field in fields]])
    return Response(content="\ufeff" + stream.getvalue(), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": 'attachment; filename="danaconnect-results.csv"', "Cache-Control": "no-store"})
