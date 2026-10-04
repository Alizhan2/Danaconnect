"""Preview-only AI requests with opt-in and human-reviewed administrative advice."""
import json
import re
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import String, cast, func, select, update
from sqlalchemy.orm import Session

from app.auth import get_current_user, has_current_consents, require_active, require_admin, secret_hash
from app.config import settings
from app.profile_state import admitted_profile
from app.database import get_db
from app.models import AuditEvent, Direction, Participation, User, utcnow
from app.models_ai import AIPreference, AIProposal, AIUsageCounter
from app.schemas.ai import ConsentInput, PreferenceInput, ProfileReview, RecommendationInput, ReviewDecision, StructureDraft, StructureInput, MentorRecommendations
from app.services.ai import ai_available, create_proposal, redact_contacts
from app.transactions import lock_users


router = APIRouter(tags=["optional-ai"])


def profile_context(db, person):
    names = db.scalars(select(Direction.name_en).where(Direction.id.in_(person.direction_ids or []))).all()
    context = {"role": person.role, "bio": (person.bio or "")[:2500], "expertise": (person.expertise or "")[:1500], "directions": list(names), "evidence_count": len(person.evidence_urls or [])}
    context = redact_contacts(context)
    if person.full_name and len(person.full_name.strip()) >= 3:
        for field in ("bio", "expertise"):
            context[field] = re.sub(re.escape(person.full_name.strip()), "[identity removed]", context[field], flags=re.IGNORECASE)
    if person.birth_date:
        for field in ("bio", "expertise"):
            for date_text in (person.birth_date.isoformat(), person.birth_date.strftime("%d.%m.%Y"), person.birth_date.strftime("%d/%m/%Y")):
                context[field] = context[field].replace(date_text, "[date removed]")
    return context


def proposal_view(proposal):
    return {"id": proposal.id, "kind": proposal.kind, "subject_user_id": proposal.subject_user_id, "model": proposal.model, "status": proposal.status, "proposal": proposal.proposal, "source_facts": proposal.source_facts, "created_at": proposal.created_at, "decided_at": proposal.decided_at, "review_reason": proposal.review_reason, "override_summary": proposal.override_summary, "advisory_only": True}


@router.get("/ai/status")
def ai_status(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    day = utcnow().date()
    counters = {row.scope_key: row.count for row in db.scalars(select(AIUsageCounter).where(AIUsageCounter.day == day, AIUsageCounter.scope_key.in_(["global", "user:" + user.id]))).all()}
    return {"available": ai_available(), "reason": None if ai_available() else "ИИ-помощник не подключён", "remaining_today": max(0, min(settings.ai_daily_user_limit - counters.get("user:" + user.id, 0), settings.ai_daily_global_limit - counters.get("global", 0))), "daily_user_limit": settings.ai_daily_user_limit, "max_input_chars": min(6000, settings.ai_max_input_chars), "external_provider": "OpenAI", "advisory_only": True}


@router.get("/me/ai-preference")
def preference(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    row = db.scalar(select(AIPreference).where(AIPreference.user_id == user.id))
    return {"allow_admin_review": bool(row and row.allow_admin_review)}


@router.put("/me/ai-preference")
def set_preference(payload: PreferenceInput, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    user = lock_users(db, [user.id])[user.id]
    row = db.scalar(select(AIPreference).where(AIPreference.user_id == user.id))
    if row is None:
        row = AIPreference(user_id=user.id)
        db.add(row)
    row.allow_admin_review, row.updated_at = payload.allow_admin_review, utcnow()
    if not payload.allow_admin_review:
        # Existing administrative proposals become inaccessible through their
        # review API; remove generated text while preserving non-content audit.
        db.execute(update(AIProposal).where(AIProposal.subject_user_id == user.id, AIProposal.kind == "profile_review", AIProposal.status.in_(["pending", "ready"])).values(status="dismissed", proposal=None, review_reason="subject_opt_out", decided_at=utcnow()))
    db.add(AuditEvent(actor_id=user.id, action="ai.preference_updated", entity_type="user", entity_id=user.id, detail={"allow_admin_review": payload.allow_admin_review}))
    db.commit()
    return {"allow_admin_review": row.allow_admin_review}


@router.post("/ai/structure")
def structure(payload: StructureInput, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if not has_current_consents(db, user, scopes=("registration",)):
        raise HTTPException(403, "Сначала подтвердите обязательные документы")
    result = create_proposal(db, requester_id=user.id, kind="structure", context={"purpose": payload.purpose, "text": payload.text}, output_class=StructureDraft, locale=payload.locale)
    return proposal_view(result)


@router.post("/ai/mentor-recommendations")
def recommendations(payload: RecommendationInput, user: User = Depends(require_active), db: Session = Depends(get_db)):
    if user.role != "mentee":
        raise HTTPException(403, "Подбор менторов доступен для менти")
    if not ai_available():
        raise HTTPException(503, "ИИ-помощник не подключён")
    direction = db.get(Direction, payload.direction_id)
    if not direction or not direction.active or direction.id not in (user.direction_ids or []):
        raise HTTPException(422, "Выберите действующее направление из вашей анкеты")
    statement = select(User).where(User.role == "mentor", User.account_status == "active", User.profile_completed.is_(True), User.intake_open.is_(True), User.capacity > 0, cast(User.direction_ids, String).contains('"' + direction.id + '"', autoescape=True)).order_by(User.created_at, User.id).limit(100)
    candidates = []
    for person in db.scalars(statement).all():
        occupied = db.scalar(select(func.count(Participation.id)).where(Participation.mentor_id == person.id, Participation.status.in_(["active", "paused"])))
        if occupied >= person.capacity or not admitted_profile(person) or not has_current_consents(db, person):
            continue
        anonymous = profile_context(db, person)
        candidates.append({"candidate_id": person.id, "expertise": anonymous["expertise"][:600], "bio": anonymous["bio"][:400]})
        if len(candidates) >= 12:
            break
    if not candidates:
        return {"id": None, "kind": "mentor_recommendation", "status": "no_candidates", "proposal": {"recommendations": [], "questions": []}, "candidates": [], "reason": "В этом направлении нет доступных менторов", "advisory_only": True}
    context = {"direction": direction.name_en, "goal": payload.goal, "skills": payload.skills, "candidates": candidates}
    # Candidate input is bounded together with the user's goal, not truncated
    # by bytes in a way that could change IDs or produce invalid JSON.
    while len(candidates) > 1 and len(json.dumps(redact_contacts(context), ensure_ascii=False)) > settings.ai_max_input_chars:
        candidates.pop()
    candidate_ids = [item["candidate_id"] for item in candidates]
    result = create_proposal(db, requester_id=user.id, kind="mentor_recommendation", context=context, output_class=MentorRecommendations, locale=payload.locale, source_facts={"candidate_ids": candidate_ids, "direction_id": direction.id}, candidate_ids=candidate_ids)
    response = proposal_view(result)
    # Eligibility is checked again after the provider call; recommendations do
    # not bypass the normal application's independent live capacity checks.
    current = []
    for explanation in response["proposal"]["recommendations"]:
        person = db.get(User, explanation["candidate_id"], populate_existing=True)
        if person and person.role == "mentor" and person.account_status == "active" and admitted_profile(person) and person.intake_open and has_current_consents(db, person):
            occupied = db.scalar(select(func.count(Participation.id)).where(Participation.mentor_id == person.id, Participation.status.in_(["active", "paused"])))
            if occupied < person.capacity and direction.id in (person.direction_ids or []):
                current.append({**explanation, "full_name": person.full_name})
    response["proposal"] = {**response["proposal"], "recommendations": current}
    return response


@router.post("/admin/ai/profile-review/{user_id}")
def profile_review(user_id: str, payload: ConsentInput, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    person = db.get(User, user_id)
    opt_in = db.scalar(select(AIPreference).where(AIPreference.user_id == user_id))
    if not person or person.role not in {"mentee", "mentor"} or person.account_status not in {"draft", "pending", "changes_requested"}:
        raise HTTPException(404, "Анкета для проверки не найдена")
    if not opt_in or not opt_in.allow_admin_review:
        raise HTTPException(403, "Участник не разрешил проверку анкеты с помощью ИИ")
    if not has_current_consents(db, person, scopes=("registration",)):
        raise HTTPException(409, "Участник должен подтвердить обязательные документы")
    context = profile_context(db, person)
    snapshot_hash = secret_hash(json.dumps(context, ensure_ascii=False, sort_keys=True))
    result = create_proposal(db, requester_id=admin.id, subject_user_id=person.id, kind="profile_review", context=context, output_class=ProfileReview, locale=payload.locale, source_facts={"profile_snapshot_hash": snapshot_hash, "account_status": person.account_status})
    opt_in = db.scalar(select(AIPreference).where(AIPreference.user_id == user_id).execution_options(populate_existing=True))
    if not opt_in or not opt_in.allow_admin_review:
        result.status, result.proposal, result.review_reason = "dismissed", None, "subject_opt_out"
        db.commit()
        raise HTTPException(403, "Участник отозвал разрешение на проверку с помощью ИИ")
    return proposal_view(result)


@router.get("/admin/ai/proposals")
def admin_proposals(limit: int = Query(50, ge=1, le=100), offset: int = Query(0, ge=0), admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    rows = db.scalars(select(AIProposal).join(AIPreference, AIPreference.user_id == AIProposal.subject_user_id).where(AIProposal.kind == "profile_review", AIPreference.allow_admin_review.is_(True)).order_by(AIProposal.created_at.desc()).limit(limit).offset(offset)).all()
    return [proposal_view(row) for row in rows]


@router.post("/admin/ai/proposals/{proposal_id}/decision")
def decide_proposal(proposal_id: str, payload: ReviewDecision, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    proposal = db.get(AIProposal, proposal_id)
    if not proposal or proposal.kind != "profile_review":
        raise HTTPException(404, "Предложение ИИ не найдено")
    # Serialize against another human decision and the participant's opt-out
    # on both SQLite and PostgreSQL, before rereading current proposal state.
    lock_users(db, [admin.id, proposal.subject_user_id])
    proposal = db.scalar(select(AIProposal).where(AIProposal.id == proposal_id).with_for_update().execution_options(populate_existing=True))
    opt_in = db.scalar(select(AIPreference).where(AIPreference.user_id == proposal.subject_user_id))
    if not opt_in or not opt_in.allow_admin_review:
        raise HTTPException(403, "Участник отозвал разрешение на проверку с помощью ИИ")
    if proposal.status != "ready":
        raise HTTPException(409, "Предложение уже обработано или недоступно")
    person = db.get(User, proposal.subject_user_id)
    if not person or secret_hash(json.dumps(profile_context(db, person), ensure_ascii=False, sort_keys=True)) != proposal.source_facts.get("profile_snapshot_hash"):
        raise HTTPException(409, "Анкета изменилась. Запросите новое предложение ИИ")
    if payload.decision == "overridden" and not (payload.override_summary or "").strip():
        raise HTTPException(422, "Укажите исправленное решение администратора")
    proposal.status, proposal.reviewer_id, proposal.review_reason = payload.decision, admin.id, payload.reason
    proposal.override_summary, proposal.decided_at = payload.override_summary, utcnow()
    db.add(AuditEvent(actor_id=admin.id, action="ai.human_decision", entity_type="ai_proposal", entity_id=proposal.id, detail={"decision": payload.decision, "reason": payload.reason}))
    # This records the review of AI advice only. Registration moderation uses
    # the existing separate endpoint and never changes here.
    db.commit()
    return proposal_view(proposal)
