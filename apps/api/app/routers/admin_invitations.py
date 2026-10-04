"""Admin admission: assured inviter, mailbox proof, then private TOTP enrollment."""
import base64
from datetime import timedelta
import io
from math import ceil
import secrets
from typing import Literal
from urllib.parse import quote, urlencode
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field, field_validator
import qrcode
from qrcode.image.svg import SvgPathFillImage
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth import aware, generate_totp_secret, matching_totp_step, require_admin, secret_hash, utcnow
from app.config import settings
from app.database import get_db
from app.delivery import DeliveryFailure, DeliveryUnavailable, decrypt_text, dispatch_email_now, encrypt_text, enqueue_email, otp_email
from app.models import AuthChallenge, SessionToken, User
from app.models_admin_invitations import AdminInvitation, AdminInvitationChallenge
from app.models_delivery import AdminCredential, EmailOutbox, SessionAssurance
from app.routers.identity import _ip_requests, _rate_lock, audit, issue_session
from app.schemas.identity import RequestCode
from app.transactions import lock_users
from app.otp_limits import lock_otp_email
from app.admin_invitation_lifecycle import close_invitation


router = APIRouter()


class InvitationInput(RequestCode):
    full_name: str = Field(min_length=2, max_length=160)
    locale: Literal["ru", "kk", "en"] = "ru"

    @field_validator("full_name", mode="before")
    @classmethod
    def trim_name(cls, value):
        return value.strip() if isinstance(value, str) else value


class InvitationToken(BaseModel):
    token: str = Field(min_length=32, max_length=128)


class InvitationCode(InvitationToken):
    challenge_id: str = Field(min_length=1, max_length=64)
    code: str = Field(pattern=r"^[0-9]{6}$")


class EnrollmentCode(BaseModel):
    enrollment_token: str = Field(min_length=32, max_length=128)
    code: str = Field(pattern=r"^[0-9]{6}$")


def require_invitation_admin(request: Request, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    # Demo/debug sessions never grant authority to create additional admins.
    session = db.scalar(select(SessionToken).where(
        SessionToken.token_hash == secret_hash(request.cookies.get("dc_session", "")),
        SessionToken.user_id == admin.id, SessionToken.expires_at > utcnow()))
    assurance = db.scalar(select(SessionAssurance.id).where(SessionAssurance.session_id == session.id)) if session else None
    credential = db.scalar(select(AdminCredential.id).where(
        AdminCredential.user_id == admin.id, AdminCredential.active.is_(True)))
    if not assurance or not credential:
        raise HTTPException(403, "Для управления администраторами войдите по email и MFA")
    return admin


def active_inviter(db, user):
    return (user is not None and user.role == "admin" and user.account_status == "active"
            and db.scalar(select(AdminCredential.id).where(
                AdminCredential.user_id == user.id, AdminCredential.active.is_(True))) is not None)


def invitation_payload(db, invitation):
    outbox = db.scalar(select(EmailOutbox).where(EmailOutbox.dedup_key == "admin-invitation:" + invitation.id))
    return {"id": invitation.id, "email": invitation.email, "full_name": invitation.full_name,
            "locale": invitation.locale, "status": invitation.status, "created_at": invitation.created_at,
            "expires_at": invitation.expires_at, "accepted_at": invitation.accepted_at,
            "delivery_status": outbox.status if outbox else None, "invited_by": invitation.invited_by}


def invitation_email(full_name, link, locale):
    templates = {
        "ru": ("DanaConnect — приглашение администратора",
               f"Здравствуйте, {full_name}!\n\nВас пригласили в команду DanaConnect с полными правами администратора. "
               "Эти права дают доступ к участникам, проектам, документам и модерации.\n\n"
               f"Примите приглашение: {link}\n\nСсылка действует 7 дней. На странице подтвердите email, "
               "затем добавьте личный QR-код в приложение-аутентификатор и введите его код. "
               "До завершения MFA доступ не предоставляется. Не пересылайте эту ссылку. "
               "Если вы не ожидали приглашения, не открывайте ссылку и обратитесь к команде DanaConnect."),
        "kk": ("DanaConnect — әкімші шақыруы",
               f"Сәлеметсіз бе, {full_name}!\n\nСіз DanaConnect командасына толық әкімші құқықтарымен шақырылдыңыз. "
               "Бұл құқықтар қатысушыларға, жобаларға, құжаттарға және модерацияға қол жеткізуге мүмкіндік береді.\n\n"
               f"Шақыруды қабылдау: {link}\n\nСілтеме 7 күн жарамды. Email мекенжайыңызды растаңыз, "
               "содан кейін жеке QR-кодты аутентификатор қолданбасына қосып, оның кодын енгізіңіз. "
               "MFA аяқталғанға дейін қолжетімділік берілмейді. Сілтемені басқа адамға жібермеңіз. "
               "Шақыруды күтпеген болсаңыз, сілтемені ашпай, DanaConnect командасына хабарласыңыз."),
        "en": ("DanaConnect — administrator invitation",
               f"Hello, {full_name}!\n\nYou have been invited to the DanaConnect team with full administrator access "
               "to participants, projects, documents, and moderation.\n\n"
               f"Accept your invitation: {link}\n\nThis link expires in 7 days. Confirm your email on the page, "
               "then add your personal QR code to an authenticator app and enter its code. "
               "Access is granted only after MFA is completed. Do not forward this link. "
               "If you did not expect this invitation, do not open the link and contact the DanaConnect team."),
    }
    return templates[locale]


def locked_admin(db, admin, request):
    admin = lock_users(db, [admin.id])[admin.id]
    if not active_inviter(db, admin):
        raise HTTPException(403, "Доступ администратора недоступен")
    require_invitation_admin(request, admin, db)
    return admin


@router.get("/admin/invitations")
def list_invitations(request: Request, admin: User = Depends(require_invitation_admin), db: Session = Depends(get_db)):
    locked_admin(db, admin, request)
    now = utcnow()
    expired = db.scalars(select(AdminInvitation).where(AdminInvitation.status == "pending",
        AdminInvitation.expires_at <= now).order_by(AdminInvitation.id).with_for_update()).all()
    for invitation in expired:
        close_invitation(db, invitation, "expired")
    db.flush()
    # Keep a stale proof hash only to return an actionable 410. The pending
    # authenticator seed no longer needs to remain after its five-minute window.
    for invitation in db.scalars(select(AdminInvitation).where(AdminInvitation.status == "pending",
        AdminInvitation.proof_expires_at <= now, AdminInvitation.encrypted_seed != "")
        .order_by(AdminInvitation.id).with_for_update()).all():
        invitation.encrypted_seed = ""
    items = db.scalars(select(AdminInvitation).order_by(AdminInvitation.created_at.desc(), AdminInvitation.id).limit(500)).all()
    result = {"items": [invitation_payload(db, item) for item in items]}
    db.commit()
    return result


@router.post("/admin/invitations", status_code=201)
def create_invitation(payload: InvitationInput, request: Request, admin: User = Depends(require_invitation_admin), db: Session = Depends(get_db)):
    admin = locked_admin(db, admin, request)
    email, now = str(payload.email).strip().lower(), utcnow()
    if db.scalar(select(User.id).where(User.email == email)):
        raise HTTPException(409, "Для этого email уже существует аккаунт. Приглашение не меняет роль или MFA")
    existing = db.scalar(select(AdminInvitation).where(AdminInvitation.email == email,
        AdminInvitation.status == "pending").with_for_update())
    if existing and aware(existing.expires_at) > now:
        raise HTTPException(409, "Для этого email уже есть действующее приглашение")
    if existing:
        close_invitation(db, existing, "expired")
        db.flush()
    token = secrets.token_urlsafe(48)
    invitation = AdminInvitation(email=email, full_name=payload.full_name, locale=payload.locale,
        invited_by=admin.id, token_hash=secret_hash(token), expires_at=now + timedelta(days=7))
    try:
        db.add(invitation)
        db.flush()
        link = settings.frontend_url.rstrip("/") + "/admin/accept-invite#token=" + token
        subject, text = invitation_email(invitation.full_name, link, invitation.locale)
        enqueue_email(db, email, subject, text, dedup_key="admin-invitation:" + invitation.id,
            locale=invitation.locale, expires_at=invitation.expires_at)
        audit(db, admin, "admin.invitation.created", "admin_invitation", invitation.id)
        db.flush()
        result = invitation_payload(db, invitation)
        db.commit()
    except DeliveryUnavailable:
        db.rollback()
        raise HTTPException(503, "Сервис отправки email не настроен") from None
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Для этого email уже есть действующее приглашение или аккаунт") from None
    return result


@router.delete("/admin/invitations/{invitation_id}")
def revoke_invitation(invitation_id: str, request: Request, admin: User = Depends(require_invitation_admin), db: Session = Depends(get_db)):
    admin = locked_admin(db, admin, request)
    invitation = db.scalar(select(AdminInvitation).where(AdminInvitation.id == invitation_id).with_for_update())
    if not invitation:
        raise HTTPException(404, "Приглашение не найдено")
    if invitation.status == "accepted":
        raise HTTPException(409, "Приглашение уже принято. Отмена приглашения не отключает аккаунт")
    if invitation.status == "pending":
        close_invitation(db, invitation, "revoked")
        audit(db, admin, "admin.invitation.revoked", "admin_invitation", invitation.id)
    db.flush()
    result = invitation_payload(db, invitation)
    db.commit()
    return result


def locked_invitation(db, *, token=None, proof=None):
    statement = select(AdminInvitation).where(AdminInvitation.token_hash == secret_hash(token)) if token else select(AdminInvitation).where(AdminInvitation.proof_hash == secret_hash(proof))
    candidate = db.scalar(statement)
    if not candidate:
        raise HTTPException(410 if proof else 400, "Приглашение или подтверждение неверно либо истекло")
    inviter_id, invitation_id = candidate.invited_by, candidate.id
    inviter = lock_users(db, [inviter_id])[inviter_id]
    # Always lock inviter first, then invitation: acceptance and revocation
    # serialize with account suspension/role changes and one another.
    invitation = db.scalar(select(AdminInvitation).where(AdminInvitation.id == invitation_id).with_for_update().execution_options(populate_existing=True))
    expected_hash = invitation.token_hash if token else invitation.proof_hash
    supplied_hash = secret_hash(token or proof)
    if not expected_hash or not secrets.compare_digest(expected_hash, supplied_hash):
        raise HTTPException(410 if proof else 400, "Приглашение или подтверждение неверно либо истекло")
    if invitation.status != "pending":
        raise HTTPException(410, "Приглашение больше не действует")
    if aware(invitation.expires_at) <= utcnow():
        close_invitation(db, invitation, "expired")
        db.commit()
        raise HTTPException(410, "Срок приглашения истёк")
    if not active_inviter(db, inviter):
        raise HTTPException(403, "Пригласивший администратор больше не имеет доступа")
    if db.scalar(select(User.id).where(User.email == invitation.email)):
        raise HTTPException(409, "Для этого email уже существует аккаунт. Обратитесь к команде платформы")
    return invitation


def request_rate_limit(request):
    now = utcnow()
    address = request.client.host if request.client else "unknown"
    with _rate_lock:
        requests = _ip_requests[address]
        while requests and requests[0] < now - timedelta(minutes=10):
            requests.popleft()
        if len(requests) >= 20:
            raise HTTPException(429, "Слишком много попыток. Повторите позже")
        requests.append(now)


@router.post("/auth/admin-invitations/request-code")
def request_invitation_code(payload: InvitationToken, request: Request, db: Session = Depends(get_db)):
    request_rate_limit(request)
    invitation = locked_invitation(db, token=payload.token)
    lock_otp_email(db, invitation.email)
    now = utcnow()
    recent_auth = db.scalar(select(func.max(AuthChallenge.created_at)).where(AuthChallenge.email == invitation.email))
    recent_invite = db.scalar(select(func.max(AdminInvitationChallenge.created_at)).where(AdminInvitationChallenge.email == invitation.email))
    if any(value and aware(value) > now - timedelta(seconds=60) for value in (recent_auth, recent_invite)):
        raise HTTPException(429, "Повторный код можно запросить через 60 секунд")
    count = sum(db.scalar(select(func.count(model.id)).where(model.email == invitation.email,
        model.created_at > now - timedelta(hours=1))) for model in (AuthChallenge, AdminInvitationChallenge))
    if count >= 10:
        raise HTTPException(429, "Слишком много кодов для этого email. Повторите позже")
    # Retire only earlier invitation challenges, never ordinary login OTPs.
    old_ids = list(db.scalars(select(AdminInvitationChallenge.id).where(
        AdminInvitationChallenge.invitation_id == invitation.id,
        AdminInvitationChallenge.consumed_at.is_(None))).all())
    db.execute(update(AdminInvitationChallenge).where(AdminInvitationChallenge.id.in_(old_ids)).values(consumed_at=now))
    db.execute(update(EmailOutbox).where(EmailOutbox.dedup_key.in_(["admin-invitation-otp:" + identifier for identifier in old_ids]),
        EmailOutbox.status.in_(["pending", "leased"])).values(status="failed", encrypted_payload="",
        lease_token=None, lease_until=None, last_error_code="otp_replaced"))
    identifier, code = str(uuid4()), f"{secrets.randbelow(1000000):06d}"
    expires_at = min(now + timedelta(minutes=settings.otp_minutes), aware(invitation.expires_at))
    challenge = AdminInvitationChallenge(id=identifier, invitation_id=invitation.id, email=invitation.email,
        code_hash=secret_hash(f"{identifier}:{code}"), expires_at=expires_at)
    db.add(challenge)
    debug = settings.auth_debug_code and settings.environment in {"development", "test"}
    try:
        if not debug:
            subject, text = otp_email(code, invitation.locale)
            mail = enqueue_email(db, invitation.email, subject, text, dedup_key="admin-invitation-otp:" + identifier,
                locale=invitation.locale, expires_at=expires_at)
        db.commit()
    except DeliveryUnavailable:
        db.rollback()
        raise HTTPException(503, "Сервис отправки email не настроен") from None
    delivery_status = "development" if debug else dispatch_email_now(db, mail.id)
    if delivery_status == "failed":
        raise HTTPException(503, "Не удалось отправить код. Проверьте адрес почты и повторите позже")
    result = {"challenge_id": identifier, "delivery_status": delivery_status,
              "email": invitation.email, "full_name": invitation.full_name,
              "expires_in": max(1, ceil((expires_at - utcnow()).total_seconds()))}
    if debug:
        result["debug_code"] = code
    return result


def qr_data_url(uri):
    # Pure Python SVG generation; the MFA secret never reaches a QR provider.
    buffer = io.BytesIO()
    qrcode.make(uri, image_factory=SvgPathFillImage, border=4).save(buffer)
    return "data:image/svg+xml;base64," + base64.b64encode(buffer.getvalue()).decode("ascii")


@router.post("/auth/admin-invitations/verify-code")
def verify_invitation_code(payload: InvitationCode, db: Session = Depends(get_db)):
    invitation = locked_invitation(db, token=payload.token)
    now = utcnow()
    invalid = HTTPException(400, "Код неверный, истёк или уже использован")
    challenge = db.scalar(select(AdminInvitationChallenge).where(
        AdminInvitationChallenge.id == payload.challenge_id,
        AdminInvitationChallenge.invitation_id == invitation.id,
        AdminInvitationChallenge.email == invitation.email).with_for_update())
    if not challenge or challenge.consumed_at or aware(challenge.expires_at) <= now or challenge.attempts >= settings.otp_max_attempts:
        raise invalid
    if not secrets.compare_digest(challenge.code_hash, secret_hash(f"{challenge.id}:{payload.code}")):
        challenge.attempts += 1
        db.commit()
        raise invalid
    consumed = db.execute(update(AdminInvitationChallenge).where(
        AdminInvitationChallenge.id == challenge.id, AdminInvitationChallenge.consumed_at.is_(None),
        AdminInvitationChallenge.attempts < settings.otp_max_attempts,
        AdminInvitationChallenge.expires_at > now).values(consumed_at=now))
    if consumed.rowcount != 1:
        db.rollback()
        raise invalid
    seed, proof = generate_totp_secret(), secrets.token_urlsafe(48)
    try:
        invitation.encrypted_seed = encrypt_text(seed)
        invitation.proof_hash = secret_hash(proof)
        invitation.proof_expires_at = min(now + timedelta(minutes=5), aware(invitation.expires_at))
        invitation.proof_attempts = 0
        uri = "otpauth://totp/" + quote("DanaConnect:" + invitation.email, safe="") + "?" + urlencode({
            "secret": seed, "issuer": "DanaConnect", "algorithm": "SHA1", "digits": 6, "period": 30})
        image = qr_data_url(uri)
        db.commit()
    except DeliveryUnavailable:
        db.rollback()
        raise HTTPException(503, "Настройка MFA временно недоступна") from None
    return {"enrollment_token": proof, "totp_uri": uri, "qr_data_url": image,
            "manual_entry_key": seed, "expires_in": max(1, int((aware(invitation.proof_expires_at) - now).total_seconds())),
            "email": invitation.email, "full_name": invitation.full_name}


@router.post("/auth/admin-invitations/accept")
def accept_invitation(payload: EnrollmentCode, response: Response, db: Session = Depends(get_db)):
    invitation = locked_invitation(db, proof=payload.enrollment_token)
    now = utcnow()
    if (not invitation.proof_expires_at or aware(invitation.proof_expires_at) <= now
            or invitation.proof_attempts >= 5 or not invitation.encrypted_seed):
        invitation.encrypted_seed = ""
        db.commit()
        raise HTTPException(410, "Время настройки MFA истекло или попытки завершены. Запросите новый код по email")
    try:
        seed = decrypt_text(invitation.encrypted_seed)
        step = matching_totp_step(seed, payload.code, -1)
    except (DeliveryFailure, DeliveryUnavailable, ValueError, TypeError):
        raise HTTPException(503, "Настройка MFA временно недоступна") from None
    if step is None:
        invitation.proof_attempts += 1
        if invitation.proof_attempts >= 5:
            invitation.encrypted_seed = ""
        db.commit()
        raise HTTPException(400, "Код приложения-аутентификатора неверный")
    try:
        user = User(email=invitation.email, full_name=invitation.full_name, preferred_locale=invitation.locale,
            role="admin", account_status="active", profile_completed=True, intake_open=False)
        db.add(user)
        db.flush()
        db.add(AdminCredential(user_id=user.id, encrypted_totp_secret=encrypt_text(seed), last_used_step=step))
        close_invitation(db, invitation, "accepted")
        invitation.accepted_at, invitation.accepted_user_id = now, user.id
        audit(db, user, "admin.invitation.accepted", "admin_invitation", invitation.id)
        return issue_session(db, user, response, mfa_verified=True)
    except DeliveryUnavailable:
        db.rollback()
        raise HTTPException(503, "Настройка MFA временно недоступна") from None
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Для этого email уже существует аккаунт или приглашение уже принято") from None
