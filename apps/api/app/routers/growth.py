from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth import get_current_user, has_current_consents, requested_locale, require_active, require_admin
from app.config import settings
from app.database import get_db
from app.models import AuditEvent, Direction, Participation, Result, User, utcnow
from app.models_growth import GrowthAward, GrowthPrivacy, LearningMaterial, PointEvent
from app.schemas.growth import AwardInput, LeaderboardPreference, MaterialInput, RevokeAward
from app.services.growth import certificate_pdf, progression, sync_user_progress

router = APIRouter(tags=["Learning and achievements"])
LEADERBOARD_VERSION = "leaderboard-v1"
TERMS = {
    "ru": "Я разрешаю показывать выбранное отображаемое имя, баллы и значки в публичном рейтинге DanaConnect. Контакты, закрытые проекты и тексты отзывов не публикуются. Участие добровольное; видимость можно отключить в любой момент.",
    "kk": "DanaConnect жария рейтингінде таңдаған атымды, ұпайларымды және белгілерімді көрсетуге рұқсат беремін. Байланыс деректері, жабық жобалар және пікір мәтіндері жарияланбайды. Қатысу ерікті; көрінуді кез келген уақытта өшіруге болады.",
    "en": "I allow my chosen display name, points, and badges to appear in the public DanaConnect leaderboard. Contacts, private projects, and feedback text are not published. Participation is voluntary; I can disable visibility at any time.",
}


def audit(db, user, action, kind, identifier, detail=None):
    db.add(AuditEvent(actor_id=user.id, action=action, entity_type=kind, entity_id=identifier, detail=detail or {}))


def commit(db):
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Запись уже существует. Обновите страницу") from None


def flush(db):
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Запись уже существует. Обновите страницу") from None


def localized(row, locale):
    title = getattr(row, "title_" + locale)
    description = getattr(row, "description_" + locale)
    actual = locale if title and description else "ru"
    return {"title": getattr(row, "title_" + actual), "description": getattr(row, "description_" + actual), "text_locale": actual}


def material_view(row, locale, admin=False):
    data = {"id": row.id, "direction_id": row.direction_id, **localized(row, locale), "url": row.url,
            "kind": row.kind, "content_language": row.content_language, "active": row.active, "updated_at": row.updated_at}
    if admin:
        data.update({field: getattr(row, field) for field in ("title_ru", "title_kk", "title_en", "description_ru", "description_kk", "description_en")})
    return data


def award_view(row, locale, admin=False):
    data = {"id": row.id, "kind": row.kind, **localized(row, locale), "result_id": row.result_id,
            "issued_at": row.issued_at, "revoked_at": row.revoked_at, "revocation_reason": row.revocation_reason,
            "certificate_available": row.kind == "certificate" and row.revoked_at is None}
    if admin:
        data.update({"user_id": row.user_id, "issued_name": row.issued_name})
        data.update({field: getattr(row, field) for field in ("title_ru", "title_kk", "title_en", "description_ru", "description_kk", "description_en")})
    return data


def preference_view(row, locale):
    return {"visible": bool(row and row.leaderboard_visible and row.consent_version == LEADERBOARD_VERSION),
            "alias": row.alias if row else "", "consent_version": row.consent_version if row else None,
            "required_version": LEADERBOARD_VERSION, "terms": TERMS[locale]}


@router.get("/materials")
def materials(request: Request, direction_id: str | None = None, kind: str | None = None,
              limit: int = Query(100, ge=1, le=200), offset: int = Query(0, ge=0), db: Session = Depends(get_db)):
    query = select(LearningMaterial).where(LearningMaterial.active.is_(True))
    if direction_id:
        query = query.where(LearningMaterial.direction_id == direction_id)
    if kind:
        query = query.where(LearningMaterial.kind == kind)
    locale = requested_locale(request)
    return [material_view(row, locale) for row in db.scalars(query.order_by(LearningMaterial.updated_at.desc(), LearningMaterial.id).offset(offset).limit(limit)).all()]


@router.get("/admin/materials")
def admin_materials(request: Request, user: User = Depends(require_admin), db: Session = Depends(get_db),
                    limit: int = Query(100, ge=1, le=200), offset: int = Query(0, ge=0)):
    return [material_view(row, requested_locale(request), True) for row in db.scalars(
        select(LearningMaterial).order_by(LearningMaterial.updated_at.desc(), LearningMaterial.id).offset(offset).limit(limit)).all()]


def check_direction(db, identifier):
    if identifier and not db.scalar(select(Direction.id).where(Direction.id == identifier, Direction.active.is_(True))):
        raise HTTPException(422, "Выберите действующее направление")


@router.post("/admin/materials", status_code=201)
def create_material(payload: MaterialInput, request: Request, user: User = Depends(require_admin), db: Session = Depends(get_db)):
    check_direction(db, payload.direction_id)
    row = LearningMaterial(**payload.model_dump(), created_by=user.id)
    db.add(row); flush(db)
    audit(db, user, "material.created", "learning_material", row.id, {"active": row.active})
    commit(db)
    return material_view(row, requested_locale(request), True)


@router.put("/admin/materials/{material_id}")
def update_material(material_id: str, payload: MaterialInput, request: Request,
                    user: User = Depends(require_admin), db: Session = Depends(get_db)):
    row = db.get(LearningMaterial, material_id)
    if not row:
        raise HTTPException(404, "Материал не найден")
    check_direction(db, payload.direction_id)
    for key, value in payload.model_dump().items():
        setattr(row, key, value)
    row.updated_at = utcnow()
    audit(db, user, "material.updated", "learning_material", row.id, {"active": row.active})
    commit(db)
    return material_view(row, requested_locale(request), True)


@router.get("/me/achievements")
def achievements(request: Request, user: User = Depends(require_active), db: Session = Depends(get_db)):
    locale = requested_locale(request, user.preferred_locale)
    events = sync_user_progress(db, user.id)
    db.commit()
    awards = db.scalars(select(GrowthAward).where(GrowthAward.user_id == user.id).order_by(GrowthAward.issued_at.desc(), GrowthAward.id)).all()
    privacy = db.scalar(select(GrowthPrivacy).where(GrowthPrivacy.user_id == user.id))
    return {**progression(events, locale), "events": [{"id": event.id, "source_type": event.source_type, "points": event.points, "earned_at": event.earned_at} for event in events],
            "awards": [award_view(row, locale) for row in awards], "leaderboard_preference": preference_view(privacy, locale),
            "demo_mode": settings.demo_mode}


@router.get("/me/leaderboard-preference")
def preference(request: Request, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return preference_view(db.scalar(select(GrowthPrivacy).where(GrowthPrivacy.user_id == user.id)), requested_locale(request, user.preferred_locale))


@router.put("/me/leaderboard-preference")
def set_preference(payload: LeaderboardPreference, request: Request, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if payload.visible:
        if user.role not in {"mentee", "mentor"} or user.account_status != "active" or not user.profile_completed or not has_current_consents(db, user):
            raise HTTPException(403, "Публичный рейтинг доступен после одобрения анкеты и документов")
        if payload.consent_version != LEADERBOARD_VERSION:
            raise HTTPException(409, "Прочитайте актуальные условия рейтинга")
    row = db.scalar(select(GrowthPrivacy).where(GrowthPrivacy.user_id == user.id).with_for_update())
    if row is None:
        row = GrowthPrivacy(user_id=user.id)
        db.add(row)
    row.leaderboard_visible = payload.visible
    row.alias = payload.alias
    row.consent_version = LEADERBOARD_VERSION if payload.visible else row.consent_version
    if payload.visible:
        row.accepted_at = utcnow()
    row.updated_at = utcnow(); flush(db)
    audit(db, user, "leaderboard.visibility", "growth_privacy", row.id, {"visible": payload.visible, "version": row.consent_version})
    if payload.visible:
        sync_user_progress(db, user.id)
    commit(db)
    return preference_view(row, requested_locale(request, user.preferred_locale))


@router.get("/leaderboard")
def leaderboard(request: Request, limit: int = Query(30, ge=1, le=100), db: Session = Depends(get_db)):
    candidates = db.execute(select(GrowthPrivacy, User).join(User, User.id == GrowthPrivacy.user_id).where(
        GrowthPrivacy.leaderboard_visible.is_(True), GrowthPrivacy.consent_version == LEADERBOARD_VERSION,
        User.account_status == "active", User.profile_completed.is_(True), User.role.in_(["mentee", "mentor"]))).all()
    entries = []
    locale = requested_locale(request)
    for privacy, user in candidates:
        if not has_current_consents(db, user):
            continue
        events = db.scalars(select(PointEvent).where(PointEvent.user_id == user.id)).all()
        # Public reads never publish contacts, account IDs, or private award details.
        progress = progression(events, locale)
        entries.append({"alias": privacy.alias, "points": progress["points"],
                        "badges": [badge["title"] for badge in progress["badges"] if badge["earned"]]})
    entries.sort(key=lambda row: (-row["points"], row["alias"].casefold()))
    return {"entries": [{"rank": index+1, **entry} for index, entry in enumerate(entries[:limit])], "demo_mode": settings.demo_mode,
            "ranking_basis": "earned_points", "visibility": "explicit_opt_in"}


@router.get("/me/portfolio")
def portfolio(request: Request, user: User = Depends(require_active), db: Session = Depends(get_db)):
    rows = db.execute(select(Result, Participation).join(Participation, Participation.id == Result.participation_id).where(
        (Participation.mentee_id == user.id) | (Participation.mentor_id == user.id),
        Result.verification_status == "verified", Result.status == "completed_successfully",
        Participation.status == "completed_successfully")).all()
    return {"visibility": "private", "results": [{"id": result.id, "summary": result.summary, "artifact_url": result.artifact_url,
                "completed_at": result.completed_at, "meeting_count": result.meeting_count} for result, _ in rows]}


@router.get("/admin/growth/users")
def eligible_users(user: User = Depends(require_admin), db: Session = Depends(get_db), limit: int = Query(100, ge=1, le=200), offset: int = Query(0, ge=0)):
    rows = db.scalars(select(User).where(User.account_status == "active", User.profile_completed.is_(True), User.role.in_(["mentee", "mentor"])).order_by(User.full_name, User.id).offset(offset).limit(limit)).all()
    return [{"id": row.id, "full_name": row.full_name, "role": row.role} for row in rows]


@router.get("/admin/awards")
def list_awards(request: Request, user: User = Depends(require_admin), db: Session = Depends(get_db), limit: int = Query(100, ge=1, le=200), offset: int = Query(0, ge=0)):
    return [award_view(row, requested_locale(request), True) for row in db.scalars(select(GrowthAward).order_by(GrowthAward.issued_at.desc(), GrowthAward.id).offset(offset).limit(limit)).all()]


@router.get("/admin/growth/results")
def award_sources(user_id: str, user: User = Depends(require_admin), db: Session = Depends(get_db), limit: int = Query(100, ge=1, le=200)):
    rows = db.scalars(select(Result).join(Participation, Participation.id == Result.participation_id).where(
        ((Participation.mentee_id == user_id) | (Participation.mentor_id == user_id)),
        Result.verification_status == "verified", Result.status == "completed_successfully",
        Participation.status == "completed_successfully").order_by(Result.completed_at.desc(), Result.id).limit(limit)).all()
    return [{"id": row.id, "summary": row.summary, "completed_at": row.completed_at} for row in rows]


@router.post("/admin/awards", status_code=201)
def create_award(payload: AwardInput, request: Request, user: User = Depends(require_admin), db: Session = Depends(get_db)):
    recipient = db.get(User, payload.user_id)
    if not recipient or recipient.role not in {"mentee", "mentor"} or recipient.account_status != "active" or not recipient.profile_completed:
        raise HTTPException(422, "Награда доступна одобренному участнику")
    if payload.result_id:
        result = db.get(Result, payload.result_id)
        participation = db.get(Participation, result.participation_id) if result else None
        if not result or not participation or recipient.id not in {participation.mentee_id, participation.mentor_id} or result.verification_status != "verified" or result.status != "completed_successfully" or participation.status != "completed_successfully":
            raise HTTPException(422, "Выберите подтверждённый результат этого участника")
    row = GrowthAward(**payload.model_dump(), issued_by=user.id, issued_name=recipient.full_name)
    db.add(row); flush(db)
    audit(db, user, "award.issued", "growth_award", row.id, {"kind": row.kind, "user_id": row.user_id, "result_id": row.result_id})
    commit(db)
    return award_view(row, requested_locale(request), True)


@router.post("/admin/awards/{award_id}/revoke")
def revoke_award(award_id: str, payload: RevokeAward, request: Request, user: User = Depends(require_admin), db: Session = Depends(get_db)):
    row = db.get(GrowthAward, award_id)
    if not row:
        raise HTTPException(404, "Награда не найдена")
    if row.revoked_at is None:
        row.revoked_at = utcnow(); row.revocation_reason = payload.reason
        audit(db, user, "award.revoked", "growth_award", row.id, {"reason": payload.reason})
        commit(db)
    return award_view(row, requested_locale(request), True)


@router.get("/me/certificates/{award_id}/download")
def download_certificate(award_id: str, request: Request, user: User = Depends(require_active), db: Session = Depends(get_db)):
    row = db.get(GrowthAward, award_id)
    if not row or row.user_id != user.id or row.kind != "certificate" or row.revoked_at is not None:
        raise HTTPException(404, "Сертификат недоступен")
    content = certificate_pdf(row, requested_locale(request, user.preferred_locale))
    return Response(content, media_type="application/pdf", headers={"Content-Disposition": f'attachment; filename="danaconnect-certificate-{row.id}.pdf"', "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"})
