import secrets
from collections import defaultdict, deque
from datetime import timedelta
from typing import Literal
import hashlib
from threading import Lock
from uuid import uuid4
import base64
from urllib.parse import unquote, urlencode, urlsplit

import httpx
import jwt

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.responses import RedirectResponse
from sqlalchemy import String, cast, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth import admin_mfa_required, aware, current_required_versions, get_current_user, has_current_consents, matching_totp_step, requested_locale, required_document_state, require_active, require_admin, secret_hash, utcnow
from app.config import settings
from app.database import get_db
from app.models import AuditEvent, AuthChallenge, Consent, Direction, Document, DocumentVersion, Notification, Participation, RegistrationReview, SessionToken, User
from app.schemas.identity import ConsentInput, DirectionInput, DirectionUpdate, IntakeInput, MFAVerify, ProfileInput, RequestCode, ReviewInput, VerifyCode
from app.transactions import lock_users
from app.otp_limits import lock_otp_email
from app.profile_state import MENTOR_COMMITMENT_VERSION, admitted_profile, profile_complete
from app.models_delivery import AdminCredential, ExternalIdentity, MFAChallenge, OAuthState, SessionAssurance
from app.models_admin_invitations import AdminInvitationChallenge
from app.delivery import DeliveryFailure, DeliveryUnavailable, decrypt_text, delivery_ready, encrypt_text, enqueue_email, google_ready, otp_email


router = APIRouter()
_ip_requests = defaultdict(deque)
_rate_lock = Lock()


def self_user(user):
    return {"id": user.id, "email": user.email, "full_name": user.full_name, "role": user.role, "account_status": user.account_status, "intake_open": user.intake_open, "timezone": user.timezone, "city": user.city, "organization": user.organization, "phone": user.phone, "birth_date": user.birth_date, "bio": user.bio, "expertise": user.expertise, "evidence_urls": user.evidence_urls or [], "direction_ids": user.direction_ids or [], "capacity": user.capacity, "profile_completed": admitted_profile(user), "mentor_commitment": user.mentor_commitment, "mentor_commitment_accepted_at": user.mentor_commitment_accepted_at, "preferred_locale": getattr(user, "preferred_locale", "ru")}


def public_mentor(user):
    return {"id": user.id, "full_name": user.full_name, "role": user.role, "city": user.city, "timezone": user.timezone, "bio": user.bio, "expertise": user.expertise, "direction_ids": user.direction_ids or [], "intake_open": user.intake_open, "capacity": user.capacity}


def direction_dict(direction):
    return {"id": direction.id, "slug": direction.slug, "name_ru": direction.name_ru, "name_kk": direction.name_kk, "name_en": direction.name_en, "description_ru": direction.description_ru, "active": direction.active}


def audit(db, actor, action, entity_type, entity_id, detail=None):
    db.add(AuditEvent(actor_id=actor.id if actor else None, action=action, entity_type=entity_type, entity_id=entity_id, detail=detail or {}))


def active_profile_directions(db, user):
    ids = set(user.direction_ids or [])
    if not ids:
        return False
    current = set(db.scalars(select(Direction.id).where(Direction.id.in_(ids), Direction.active.is_(True))).all())
    return ids == current


def catalog_eligible(db, user, active_directions):
    return (user.role == "mentor" and user.account_status == "active"
            and user.profile_completed and profile_complete(user)
            and bool(set(user.direction_ids or []) & active_directions)
            and has_current_consents(db, user))


@router.post("/auth/request-code")
def request_code(payload: RequestCode, request: Request, db: Session = Depends(get_db)):
    debug = settings.auth_debug_code and settings.environment in {"development", "test"}
    if not debug and not delivery_ready():
        raise HTTPException(503, "Сервис отправки email не настроен")
    email = str(payload.email).lower().strip()
    now = utcnow()
    # A process limiter complements the persisted email limiter in local mode.
    address = request.client.host if request.client else "unknown"
    with _rate_lock:
        requests = _ip_requests[address]
        while requests and requests[0] < now - timedelta(minutes=10):
            requests.popleft()
        if len(requests) >= 20:
            raise HTTPException(429, "Слишком много попыток. Повторите позже")
        requests.append(now)
    lock_otp_email(db, email)
    now = utcnow()
    recent = db.scalar(select(AuthChallenge).where(AuthChallenge.email == email).order_by(AuthChallenge.created_at.desc()).limit(1))
    recent_invitation = db.scalar(select(func.max(AdminInvitationChallenge.created_at)).where(AdminInvitationChallenge.email == email))
    if ((recent and aware(recent.created_at) > now - timedelta(seconds=60))
            or (recent_invitation and aware(recent_invitation) > now - timedelta(seconds=60))):
        raise HTTPException(429, "Повторный код можно запросить через 60 секунд")
    count = db.scalar(select(func.count(AuthChallenge.id)).where(AuthChallenge.email == email, AuthChallenge.created_at > now - timedelta(hours=1)))
    count += db.scalar(select(func.count(AdminInvitationChallenge.id)).where(AdminInvitationChallenge.email == email, AdminInvitationChallenge.created_at > now - timedelta(hours=1)))
    if count >= 10:
        raise HTTPException(429, "Слишком много кодов для этого email. Повторите позже")
    challenge_id = str(uuid4())
    code = f"{secrets.randbelow(1000000):06d}"
    db.execute(update(AuthChallenge).where(AuthChallenge.email == email, AuthChallenge.consumed_at.is_(None)).values(consumed_at=now))
    challenge = AuthChallenge(id=challenge_id, email=email, code_hash=secret_hash(f"{challenge_id}:{code}"), expires_at=now + timedelta(minutes=settings.otp_minutes), attempts=0)
    db.add(challenge)
    if not debug:
        existing_user = db.scalar(select(User).where(User.email == email))
        locale = payload.locale or requested_locale(request, getattr(existing_user, "preferred_locale", "ru"))
        subject, text = otp_email(code, locale)
        try:
            enqueue_email(db, email, subject, text, dedup_key="auth-otp:" + challenge_id, locale=locale, expires_at=challenge.expires_at)
        except DeliveryUnavailable:
            db.rollback()
            raise HTTPException(503, "Сервис отправки email не настроен")
    db.commit()
    result = {"challenge_id": challenge_id, "delivery_status": "development" if debug else "queued"}
    if debug:
        result["debug_code"] = code
    return result


def issue_session(db, user, response, *, mfa_verified=False):
    token = secrets.token_urlsafe(48)
    session = SessionToken(user_id=user.id, token_hash=secret_hash(token), expires_at=utcnow() + timedelta(days=settings.session_days))
    db.add(session)
    db.flush()
    if mfa_verified:
        db.add(SessionAssurance(session_id=session.id))
    audit(db, user, "auth.login", "user", user.id, {"mfa": mfa_verified})
    db.commit()
    response.set_cookie("dc_session", token, max_age=settings.session_days * 86400, httponly=True, secure=settings.environment == "production", samesite="lax", path="/")
    return self_user(user)


@router.post("/auth/verify-code")
def verify_code(payload: VerifyCode, request: Request, response: Response, db: Session = Depends(get_db)):
    challenge = db.get(AuthChallenge, payload.challenge_id)
    now = utcnow()
    invalid = HTTPException(400, "Код неверный, истёк или уже использован")
    if not challenge or challenge.consumed_at or aware(challenge.expires_at) <= now or challenge.attempts >= settings.otp_max_attempts:
        raise invalid
    matches = secrets.compare_digest(challenge.code_hash, secret_hash(f"{challenge.id}:{payload.code}"))
    if not matches:
        db.execute(update(AuthChallenge).where(AuthChallenge.id == challenge.id, AuthChallenge.consumed_at.is_(None)).values(attempts=AuthChallenge.attempts + 1))
        db.commit()
        raise invalid
    consumed = db.execute(update(AuthChallenge).where(AuthChallenge.id == challenge.id, AuthChallenge.consumed_at.is_(None), AuthChallenge.attempts < settings.otp_max_attempts, AuthChallenge.expires_at > now).values(consumed_at=now))
    if consumed.rowcount != 1:
        db.rollback()
        raise invalid
    user = db.scalar(select(User).where(User.email == challenge.email))
    if not user:
        user = User(email=challenge.email, preferred_locale=requested_locale(request))
        db.add(user)
        db.flush()
    if user.account_status == "suspended":
        db.commit()
        raise HTTPException(403, "Аккаунт недоступен")
    if admin_mfa_required(db, user):
        credential = db.scalar(select(AdminCredential).where(AdminCredential.user_id == user.id, AdminCredential.active.is_(True)))
        if credential is None:
            db.commit()
            raise HTTPException(503, "Администратору нужно настроить MFA через оператора платформы")
        mfa_token = secrets.token_urlsafe(48)
        db.execute(update(MFAChallenge).where(MFAChallenge.user_id == user.id, MFAChallenge.consumed_at.is_(None)).values(consumed_at=now))
        db.add(MFAChallenge(user_id=user.id, token_hash=secret_hash(mfa_token), expires_at=now + timedelta(minutes=settings.admin_mfa_minutes)))
        db.commit()
        return {"mfa_required": True, "mfa_challenge_id": mfa_token, "method": "totp", "expires_in": settings.admin_mfa_minutes * 60}
    return issue_session(db, user, response)


@router.post("/auth/mfa/verify")
def verify_mfa(payload: MFAVerify, response: Response, db: Session = Depends(get_db)):
    now = utcnow()
    invalid = HTTPException(400, "Код подтверждения неверный или истёк")
    challenge = db.scalar(select(MFAChallenge).where(MFAChallenge.token_hash == secret_hash(payload.mfa_challenge_id)))
    if challenge and (challenge.consumed_at or aware(challenge.expires_at) <= now or challenge.attempts >= settings.otp_max_attempts):
        raise HTTPException(410, "Время подтверждения MFA истекло или попытки завершены. Запросите новый код по email. Повторно сканировать QR не нужно.")
    if not challenge:
        raise invalid
    user = lock_users(db, [challenge.user_id]).get(challenge.user_id)
    if not user or user.role != "admin" or user.account_status != "active":
        raise invalid
    credential = db.scalar(select(AdminCredential).where(AdminCredential.user_id == user.id, AdminCredential.active.is_(True)))
    if not credential:
        raise invalid
    try:
        step = matching_totp_step(decrypt_text(credential.encrypted_totp_secret), payload.code, credential.last_used_step)
    except (DeliveryFailure, DeliveryUnavailable):
        raise HTTPException(503, "MFA временно недоступна. Обратитесь к оператору")
    if step is None:
        db.execute(update(MFAChallenge).where(MFAChallenge.id == challenge.id, MFAChallenge.consumed_at.is_(None)).values(attempts=MFAChallenge.attempts + 1))
        db.commit()
        raise invalid
    consumed = db.execute(update(MFAChallenge).where(MFAChallenge.id == challenge.id, MFAChallenge.consumed_at.is_(None), MFAChallenge.attempts < settings.otp_max_attempts, MFAChallenge.expires_at > now).values(consumed_at=now))
    updated = db.execute(update(AdminCredential).where(AdminCredential.id == credential.id, AdminCredential.active.is_(True), AdminCredential.last_used_step < step).values(last_used_step=step))
    if consumed.rowcount != 1 or updated.rowcount != 1:
        db.rollback()
        raise invalid
    return issue_session(db, user, response, mfa_verified=True)


@router.get("/auth/providers")
def auth_providers():
    return {"email": delivery_ready() or (settings.auth_debug_code and settings.environment != "production"), "google": google_ready(), "admin_mfa": True}


def safe_participant_return(value):
    """Keep OAuth navigation on the participant app, including encoded inputs."""
    if not isinstance(value, str) or not value.startswith("/") or len(value) > 2048:
        return "/dashboard"
    decoded = value
    for _ in range(3):
        decoded = unquote(decoded)
    if decoded.startswith("//") or any(ord(char) < 32 or char == "\\" for char in decoded):
        return "/dashboard"
    try:
        parsed, checked = urlsplit(value), urlsplit(decoded)
    except ValueError:
        return "/dashboard"
    if parsed.netloc or parsed.scheme or checked.netloc or checked.scheme:
        return "/dashboard"
    # Do not carry auth loops, operator URLs, API routes or dot-segment tricks.
    path = checked.path
    if path in {"/login", "/register", "/onboarding"} or path.startswith(("/api/", "/admin")) or any(part in {".", ".."} for part in path.split("/")):
        return "/dashboard"
    return parsed.geturl()


@router.get("/auth/google/start")
def google_start(response: Response, locale: str = Query(default="ru", pattern=r"^(ru|kk|en)$"),
    role: Literal["mentor", "mentee"] | None = None, return_to: str = Query(default="/dashboard", max_length=2048), db: Session = Depends(get_db)):
    if not google_ready():
        raise HTTPException(503, "Вход через Google не настроен")
    state, nonce, browser, verifier = (secrets.token_urlsafe(48) for _ in range(4))
    db.add(OAuthState(state_hash=secret_hash(state), nonce_hash=secret_hash(nonce), browser_hash=secret_hash(browser), encrypted_verifier=encrypt_text(verifier), locale=locale, registration_role=role, return_to=safe_participant_return(return_to), expires_at=utcnow() + timedelta(minutes=10)))
    db.commit()
    response.set_cookie("dc_oauth", browser, max_age=600, httponly=True, secure=settings.environment == "production", samesite="lax", path="/")
    parameters = {"client_id": settings.google_client_id, "redirect_uri": settings.google_redirect_uri, "response_type": "code", "scope": "openid email profile", "state": state, "nonce": nonce, "code_challenge": base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("="), "code_challenge_method": "S256", "prompt": "select_account"}
    return {"authorization_url": "https://accounts.google.com/o/oauth2/v2/auth?" + urlencode(parameters)}


def verify_google_id_token(token: str, nonce_hash: str):
    try:
        signing_key = jwt.PyJWKClient("https://www.googleapis.com/oauth2/v3/certs", timeout=10).get_signing_key_from_jwt(token)
        claims = jwt.decode(token, signing_key.key, algorithms=["RS256"], audience=settings.google_client_id, issuer=["https://accounts.google.com", "accounts.google.com"], options={"require": ["exp", "iat", "iss", "aud", "sub", "nonce", "email", "email_verified"]}, leeway=15)
        if claims.get("email_verified") is not True or not isinstance(claims.get("nonce"), str) or not secrets.compare_digest(secret_hash(claims["nonce"]), nonce_hash):
            raise ValueError()
        if claims.get("azp", settings.google_client_id) != settings.google_client_id:
            raise ValueError()
        if isinstance(claims["aud"], list) and len(claims["aud"]) > 1 and claims.get("azp") != settings.google_client_id:
            raise ValueError()
        email = str(claims["email"]).lower()
        # Google is authoritative for Gmail or a verified Workspace domain.
        domain = email.rsplit("@", 1)[-1]
        if domain != "gmail.com" and claims.get("hd") != domain:
            raise ValueError()
        if not isinstance(claims["sub"], str) or not claims["sub"] or len(claims["sub"]) > 255:
            raise ValueError()
        return claims
    except (jwt.PyJWTError, ValueError, TypeError, KeyError):
        raise HTTPException(400, "Не удалось подтвердить аккаунт Google. Используйте вход по email") from None


@router.get("/auth/google/callback")
def google_callback(request: Request, state: str = Query(max_length=128), code: str = Query(max_length=4096), db: Session = Depends(get_db)):
    if not google_ready():
        raise HTTPException(503, "Вход через Google не настроен")
    browser = request.cookies.get("dc_oauth", "")
    oauth = db.scalar(select(OAuthState).where(OAuthState.state_hash == secret_hash(state)))
    now = utcnow()
    if not oauth or not browser or not secrets.compare_digest(oauth.browser_hash, secret_hash(browser)) or oauth.consumed_at or aware(oauth.expires_at) <= now:
        raise HTTPException(400, "Сессия входа через Google истекла. Повторите вход")
    consumed = db.execute(update(OAuthState).where(OAuthState.id == oauth.id, OAuthState.consumed_at.is_(None), OAuthState.expires_at > now).values(consumed_at=now))
    if consumed.rowcount != 1:
        db.rollback()
        raise HTTPException(400, "Сессия входа через Google уже использована")
    verifier, nonce_hash, locale = decrypt_text(oauth.encrypted_verifier), oauth.nonce_hash, oauth.locale
    registration_role, return_to = oauth.registration_role, safe_participant_return(oauth.return_to)
    oauth.encrypted_verifier = ""
    db.commit()
    try:
        token_response = httpx.post("https://oauth2.googleapis.com/token", data={"client_id": settings.google_client_id, "client_secret": settings.google_client_secret, "redirect_uri": settings.google_redirect_uri, "grant_type": "authorization_code", "code": code, "code_verifier": verifier}, timeout=10)
        if token_response.status_code != 200:
            raise ValueError()
        id_token = token_response.json()["id_token"]
        if not isinstance(id_token, str):
            raise ValueError()
    except (httpx.HTTPError, ValueError, KeyError, TypeError):
        raise HTTPException(400, "Не удалось завершить вход через Google") from None
    claims = verify_google_id_token(id_token, nonce_hash)
    identity = db.scalar(select(ExternalIdentity).where(ExternalIdentity.provider == "google", ExternalIdentity.subject == claims["sub"]))
    user = db.get(User, identity.user_id) if identity else db.scalar(select(User).where(User.email == str(claims["email"]).lower()))
    if user and user.role == "admin":
        # Administrators always use the dedicated email + provisioned TOTP flow.
        raise HTTPException(403, "Для администратора используйте вход по email и MFA")
    if user and user.account_status == "suspended":
        raise HTTPException(403, "Аккаунт недоступен")
    if not user:
        user = User(email=str(claims["email"]).lower(), preferred_locale=locale)
        db.add(user)
        db.flush()
    if not identity:
        db.add(ExternalIdentity(user_id=user.id, provider="google", subject=claims["sub"]))
    destination = return_to
    if user.role == "unchosen" or not admitted_profile(user):
        parameters = {"returnTo": return_to}
        hinted_role = user.role if user.role in {"mentor", "mentee"} else registration_role
        if hinted_role in {"mentor", "mentee"}:
            parameters["role"] = hinted_role
        destination = "/onboarding?" + urlencode(parameters)
    response = RedirectResponse(settings.frontend_url.rstrip("/") + destination, status_code=303)
    response.delete_cookie("dc_oauth", path="/")
    issue_session(db, user, response)
    return response


@router.post("/auth/logout")
def logout(request: Request, response: Response, db: Session = Depends(get_db)):
    token = request.cookies.get("dc_session")
    if token:
        session = db.scalar(select(SessionToken).where(SessionToken.token_hash == secret_hash(token)))
        if session:
            db.delete(session)
            db.commit()
    response.delete_cookie("dc_session", path="/", secure=settings.environment == "production", httponly=True, samesite="lax")
    return {"ok": True}


@router.get("/auth/me")
def me(user: User = Depends(get_current_user)):
    return self_user(user)


@router.put("/me/profile")
def save_profile(payload: ProfileInput, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    user_id = user.id
    user = lock_users(db, [user_id])[user_id]
    if user.account_status == "suspended":
        raise HTTPException(403, "Аккаунт недоступен")
    if payload.role and user.role not in {"unchosen", payload.role}:
        raise HTTPException(403, "Изменить роль может только администратор")
    if user.role == "unchosen" and not payload.role:
        raise HTTPException(422, "Выберите роль")
    role = payload.role or user.role
    if role == "mentor" and len(payload.expertise.strip()) < 10:
        raise HTTPException(422, "Опишите вашу экспертизу минимум в 10 символах")
    if role == "mentor":
        occupied = db.scalar(select(func.count(Participation.id)).where(Participation.mentor_id == user.id, Participation.status.in_(["active", "paused"])))
        if payload.capacity < occupied:
            raise HTTPException(409, "Вместимость не может быть меньше числа текущих участников")
    direction_ids = list(dict.fromkeys(payload.direction_ids))
    active_ids = set(db.scalars(select(Direction.id).where(Direction.id.in_(direction_ids), Direction.active.is_(True))).all())
    if active_ids != set(direction_ids):
        raise HTTPException(422, "Выберите действующие направления")
    values = payload.model_dump(exclude={"role", "evidence_urls", "mentor_commitment"}, exclude_none=True)
    # Optional personal fields must remain clearable.
    values["phone"], values["birth_date"] = payload.phone, payload.birth_date
    values["direction_ids"] = direction_ids
    values["evidence_urls"] = [str(url) for url in payload.evidence_urls]
    values["mentor_commitment"] = role == "mentor" and payload.mentor_commitment
    accepted_at = user.mentor_commitment_accepted_at
    newly_accepted = values["mentor_commitment"] and (user.role != "mentor" or not user.mentor_commitment or accepted_at is None)
    values["mentor_commitment_accepted_at"] = (utcnow() if newly_accepted else accepted_at) if values["mentor_commitment"] else None
    review_fields = {"full_name", "city", "phone", "birth_date", "organization", "bio", "expertise", "evidence_urls", "direction_ids", "capacity", "mentor_commitment", "mentor_commitment_accepted_at"}
    needs_review = user.role == "unchosen" or any(getattr(user, name) != values[name] for name in review_fields)
    for name, value in values.items():
        setattr(user, name, value)
    if user.role != "admin":
        user.role = role
        if needs_review or not profile_complete(user):
            user.account_status = "draft"
            user.intake_open = False
    user.profile_completed = profile_complete(user)
    audit(db, user, "profile.updated", "user", user.id)
    if newly_accepted:
        audit(db, user, "mentor_commitment.accepted", "user", user.id, {"version": MENTOR_COMMITMENT_VERSION})
    db.commit()
    return self_user(user)


@router.post("/me/submit-registration")
def submit_registration(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    user_id = user.id
    user = lock_users(db, [user_id])[user_id]
    if user.account_status == "suspended":
        raise HTTPException(403, "Аккаунт недоступен")
    if user.role not in {"mentee", "mentor"} or not user.profile_completed or not profile_complete(user):
        raise HTTPException(409, "Сначала заполните анкету")
    if user.account_status not in {"draft", "changes_requested"}:
        raise HTTPException(409, "Анкета уже отправлена или одобрена")
    if not active_profile_directions(db, user):
        raise HTTPException(409, "Выберите действующие направления")
    if not required_document_state(db, user)[0]:
        raise HTTPException(503, "Обязательные документы ещё не опубликованы командой платформы. Отправка анкеты станет доступна после публикации.")
    if not has_current_consents(db, user):
        raise HTTPException(409, "Подтвердите все обязательные документы")
    user.account_status = "pending"
    audit(db, user, "registration.submitted", "user", user.id)
    db.commit()
    return self_user(user)


@router.get("/me/registration-requirements")
def registration_requirements(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    configured, versions = required_document_state(db, user)
    accepted = set(db.scalars(select(Consent.document_version_id).where(Consent.user_id == user.id)).all())
    required_ids = [version.id for version in versions]
    return {"documents_configured": configured,
            "required_version_ids": required_ids,
            "unaccepted_version_ids": [identifier for identifier in required_ids if identifier not in accepted]}


def localized_document(version, locale):
    translated = getattr(version, "content_" + locale, None) if locale in {"kk", "en"} else None
    content_locale = locale if translated else "ru"
    content = translated or version.content
    return content, content_locale, hashlib.sha256(content.encode()).hexdigest()


@router.get("/documents")
def documents(request: Request, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    required_ids = {version.id for version in current_required_versions(db, user)}
    accepted = set(db.scalars(select(Consent.document_version_id).where(Consent.user_id == user.id)).all())
    locale = requested_locale(request, getattr(user, "preferred_locale", "ru"))
    result = []
    for document in db.scalars(select(Document).where(Document.active.is_(True))).all():
        if document.required_roles and user.role not in document.required_roles:
            continue
        if document.direction_id and document.direction_id not in (user.direction_ids or []):
            continue
        version = db.scalar(select(DocumentVersion).where(DocumentVersion.document_id == document.id).order_by(DocumentVersion.published_at.desc(), DocumentVersion.id.desc()).limit(1))
        if version:
            content, content_locale, content_hash = localized_document(version, locale)
            result.append({"id": version.id, "document_id": document.id, "title": document.title, "slug": document.slug, "version": version.version, "content": content, "content_locale": content_locale, "content_hash": content_hash, "scope": document.scope, "required": version.id in required_ids, "accepted": version.id in accepted})
    return result


@router.post("/documents/{version_id}/consent")
def accept_document(version_id: str, request: Request, payload: ConsentInput | None = None, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    version = db.get(DocumentVersion, version_id)
    document = db.get(Document, version.document_id) if version else None
    if not document or not document.active:
        raise HTTPException(404, "Документ не найден")
    if (document.required_roles and user.role not in document.required_roles) or (document.direction_id and document.direction_id not in (user.direction_ids or [])):
        raise HTTPException(403, "Документ не относится к вашей анкете")
    latest = db.scalar(select(DocumentVersion.id).where(DocumentVersion.document_id == document.id).order_by(DocumentVersion.published_at.desc(), DocumentVersion.id.desc()).limit(1))
    if latest != version_id:
        raise HTTPException(409, "Опубликована новая версия. Обновите документы")
    locale = payload.content_locale if payload else requested_locale(request, getattr(user, "preferred_locale", "ru"))
    _, content_locale, content_hash = localized_document(version, locale)
    if payload:
        if payload.content_locale != content_locale or not secrets.compare_digest(payload.content_hash, content_hash):
            raise HTTPException(409, "Документ изменился или показан на другом языке. Обновите документ")
    elif settings.environment == "production" or content_locale != "ru":
        raise HTTPException(409, "Обновите документ перед подтверждением согласия")
    existing = db.scalar(select(Consent).where(Consent.user_id == user.id, Consent.document_version_id == version_id))
    if not existing:
        existing = Consent(user_id=user.id, document_version_id=version_id, method="authenticated_checkbox", ip_address=request.client.host if request.client else None, user_agent=request.headers.get("user-agent", "")[:1000], locale=content_locale, presented_content_hash=content_hash)
        db.add(existing)
        audit(db, user, "document.accepted", "document_version", version_id)
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            existing = db.scalar(select(Consent).where(Consent.user_id == user.id, Consent.document_version_id == version_id))
            if not existing:
                raise HTTPException(409, "Не удалось сохранить согласие. Повторите")
    return {"id": existing.id, "document_version_id": existing.document_version_id, "accepted_at": existing.accepted_at, "method": existing.method}


@router.get("/directions")
def directions(db: Session = Depends(get_db)):
    return [direction_dict(item) for item in db.scalars(select(Direction).where(Direction.active.is_(True)).order_by(Direction.name_ru)).all()]


@router.get("/mentors")
def mentors(direction_id: str | None = None, q: str = Query(default="", max_length=160), limit: int = Query(default=30, ge=1, le=100), offset: int = Query(default=0, ge=0), db: Session = Depends(get_db)):
    active_directions = set(db.scalars(select(Direction.id).where(Direction.active.is_(True))).all())
    if not active_directions or (direction_id and direction_id not in active_directions):
        return []
    statement = select(User).where(User.role == "mentor", User.account_status == "active", User.profile_completed.is_(True))
    if q:
        statement = statement.where(User.full_name.ilike(f"%{q}%") | User.expertise.ilike(f"%{q}%"))
    if direction_id:
        statement = statement.where(cast(User.direction_ids, String).contains(f'"{direction_id}"', autoescape=True))
    # Consent applicability is per participant. Apply pagination after this
    # eligibility filter so stale consent rows never leave empty page holes.
    items, skipped = [], 0
    for item in db.scalars(statement.order_by(User.full_name, User.id)).yield_per(100):
        if not catalog_eligible(db, item, active_directions):
            continue
        if skipped < offset:
            skipped += 1
            continue
        items.append(public_mentor(item))
        if len(items) >= limit:
            break
    return items


@router.get("/mentors/{user_id}")
def mentor(user_id: str, db: Session = Depends(get_db)):
    user = db.get(User, user_id)
    active_directions = set(db.scalars(select(Direction.id).where(Direction.active.is_(True))).all())
    if not user or not catalog_eligible(db, user, active_directions):
        raise HTTPException(404, "Ментор не найден")
    return public_mentor(user)


@router.patch("/me/intake")
def change_intake(payload: IntakeInput, user: User = Depends(require_active), db: Session = Depends(get_db)):
    user_id = user.id
    user = lock_users(db, [user_id])[user_id]
    if user.account_status != "active" or not admitted_profile(user) or not has_current_consents(db, user):
        raise HTTPException(403, "Подтвердите актуальные документы и статус анкеты")
    if user.role != "mentor":
        raise HTTPException(403, "Набором управляет ментор")
    occupied = db.scalar(select(func.count(Participation.id)).where(Participation.mentor_id == user.id, Participation.status.in_(["active", "paused"])))
    if payload.capacity is not None and payload.capacity < occupied:
        raise HTTPException(409, "Вместимость не может быть меньше числа текущих участников")
    if payload.intake_open and (payload.capacity if payload.capacity is not None else user.capacity) == 0:
        raise HTTPException(409, "Для открытия набора задайте вместимость больше нуля")
    user.intake_open = payload.intake_open
    if payload.capacity is not None:
        user.capacity = payload.capacity
    audit(db, user, "intake.updated", "user", user.id)
    db.commit()
    return self_user(user)


@router.get("/admin/registrations")
def registrations(limit: int = Query(default=50, ge=1, le=100), offset: int = Query(default=0, ge=0),
    role: Literal["mentor", "mentee"] | None = None, direction_id: str | None = Query(default=None, min_length=1, max_length=36),
    admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    statement = select(User).where(User.account_status == "pending")
    if role:
        statement = statement.where(User.role == role)
    if direction_id:
        statement = statement.where(cast(User.direction_ids, String).contains('"' + direction_id + '"', autoescape=True))
    return [self_user(user) for user in db.scalars(statement.order_by(User.created_at, User.id).limit(limit).offset(offset)).all()]


@router.post("/admin/registrations/{user_id}/review")
def review_registration(user_id: str, payload: ReviewInput, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    admin_id = admin.id
    locked = lock_users(db, [admin_id, user_id])
    user, admin = locked[user_id], locked[admin_id]
    if admin.role != "admin" or admin.account_status != "active" or not has_current_consents(db, admin):
        raise HTTPException(403, "Доступ разрешён только администратору")
    if user.id == admin.id or user.role not in {"mentor", "mentee"} or user.account_status != "pending":
        raise HTTPException(409, "Эту анкету нельзя проверить")
    if payload.decision == "changes_requested" and not payload.reason.strip():
        raise HTTPException(422, "Укажите, что нужно исправить")
    if payload.decision == "approved" and (not user.profile_completed or not profile_complete(user) or not active_profile_directions(db, user) or not has_current_consents(db, user)):
        raise HTTPException(409, "Анкета или обязательные согласия не актуальны")
    user.account_status = "active" if payload.decision == "approved" else "changes_requested"
    db.add(RegistrationReview(user_id=user.id, admin_id=admin.id, decision=payload.decision, reason=payload.reason.strip()))
    db.add(Notification(user_id=user.id, kind="registration", title="Анкета одобрена" if payload.decision == "approved" else "Анкета требует исправлений", body=payload.reason.strip()))
    audit(db, admin, "registration.reviewed", "user", user.id, {"decision": payload.decision, "reason": payload.reason.strip()})
    db.commit()
    return self_user(user)


@router.get("/admin/directions")
def admin_directions(admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    return [direction_dict(item) for item in db.scalars(select(Direction).order_by(Direction.name_ru)).all()]


@router.post("/admin/directions", status_code=201)
def create_direction(payload: DirectionInput, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    direction = Direction(**payload.model_dump())
    db.add(direction)
    try:
        db.flush()
        audit(db, admin, "direction.created", "direction", direction.id)
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Направление с таким адресом уже существует")
    return direction_dict(direction)


@router.patch("/admin/directions/{direction_id}")
def update_direction(direction_id: str, payload: DirectionUpdate, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    direction = db.get(Direction, direction_id)
    if not direction:
        raise HTTPException(404, "Направление не найдено")
    values = payload.model_dump(exclude_none=True)
    for name, value in values.items():
        setattr(direction, name, value)
    audit(db, admin, "direction.updated", "direction", direction.id, values)
    db.commit()
    return direction_dict(direction)


@router.get("/notifications")
def notifications(limit: int = Query(default=50, ge=1, le=100), offset: int = Query(default=0, ge=0), user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    items = db.scalars(select(Notification).where(Notification.user_id == user.id).order_by(Notification.created_at.desc()).limit(limit).offset(offset)).all()
    return [{"id": item.id, "kind": item.kind, "title": item.title, "body": item.body, "read_at": item.read_at, "created_at": item.created_at} for item in items]


@router.patch("/notifications/{notification_id}/read")
def read_notification(notification_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    notification = db.get(Notification, notification_id)
    if not notification or notification.user_id != user.id:
        raise HTTPException(404, "Уведомление не найдено")
    if not notification.read_at:
        notification.read_at = utcnow()
        db.commit()
    return {"id": notification.id, "read_at": notification.read_at}
