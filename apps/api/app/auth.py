import hashlib
import hmac
import base64
import secrets
import struct
import time
from datetime import datetime, timezone

from fastapi import Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models import Consent, Document, DocumentVersion, SessionToken, User
from app.models_delivery import AdminCredential, SessionAssurance
from app.profile_state import admitted_profile


def utcnow():
    return datetime.now(timezone.utc)


def aware(value):
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


def secret_hash(value: str) -> str:
    return hmac.new(settings.auth_secret.encode(), value.encode(), hashlib.sha256).hexdigest()


def get_current_user(request: Request, db: Session = Depends(get_db)) -> User:
    token = request.cookies.get("dc_session")
    if not token:
        raise HTTPException(401, "Войдите в аккаунт")
    session = db.scalar(select(SessionToken).where(SessionToken.token_hash == secret_hash(token)))
    if session is None or aware(session.expires_at) <= utcnow():
        raise HTTPException(401, "Сессия истекла. Войдите снова")
    user = db.get(User, session.user_id)
    if user is None or user.account_status == "suspended":
        raise HTTPException(403, "Аккаунт недоступен")
    if user.role == "admin" and admin_mfa_required(db, user):
        assurance = db.scalar(select(SessionAssurance).where(SessionAssurance.session_id == session.id))
        if assurance is None:
            raise HTTPException(403, "Администратору требуется двухфакторная аутентификация")
    return user


def admin_mfa_required(db: Session, user: User) -> bool:
    if user.role != "admin":
        return False
    provisioned = db.scalar(select(AdminCredential.id).where(AdminCredential.user_id == user.id, AdminCredential.active.is_(True)))
    # Existing synthetic local sessions retain their explicitly enabled demo flow.
    return bool(provisioned) or settings.environment == "production" or not settings.auth_debug_code


def generate_totp_secret() -> str:
    return base64.b32encode(secrets.token_bytes(20)).decode().rstrip("=")


def totp_code(secret: str, step: int | None = None) -> str:
    step = int(time.time() // 30) if step is None else step
    key = base64.b32decode(secret + "=" * (-len(secret) % 8), casefold=True)
    digest = hmac.new(key, struct.pack(">Q", step), hashlib.sha1).digest()
    offset = digest[-1] & 15
    number = (struct.unpack(">I", digest[offset:offset + 4])[0] & 0x7fffffff) % 1000000
    return f"{number:06d}"


def matching_totp_step(secret: str, code: str, last_step: int) -> int | None:
    current = int(time.time() // 30)
    for step in (current, current - 1, current + 1):
        if step > last_step and secrets.compare_digest(totp_code(secret, step), code):
            return step
    return None


def requested_locale(request: Request, fallback: str = "ru") -> str:
    # Use the first supported language from the caller's explicit preferences.
    for part in request.headers.get("accept-language", "").split(","):
        language = part.split(";", 1)[0].strip().lower().split("-", 1)[0]
        if language in {"ru", "kk", "en"}:
            return language
    return fallback if fallback in {"ru", "kk", "en"} else "ru"


def applicable_required_documents(db: Session, user: User, scopes=("registration", "intake")) -> list[Document]:
    documents = db.scalars(select(Document).where(Document.active.is_(True), Document.scope.in_(scopes))).all()
    return [document for document in documents
        if (not document.required_roles or user.role in document.required_roles)
        and (not document.direction_id or document.direction_id in (user.direction_ids or []))]


def required_document_state(db: Session, user: User, scopes=("registration", "intake")) -> tuple[bool, list[DocumentVersion]]:
    documents = applicable_required_documents(db, user, scopes)
    versions = []
    for document in documents:
        version = db.scalar(select(DocumentVersion).where(DocumentVersion.document_id == document.id).order_by(DocumentVersion.published_at.desc(), DocumentVersion.id.desc()).limit(1))
        if version:
            versions.append(version)
    configured = len(versions) == len(documents)
    if settings.environment == "production" and user.role != "admin":
        for scope in ("registration", "showcase"):
            if scope in scopes and not any(document.scope == scope for document in documents):
                configured = False
    return configured, versions


def current_required_versions(db: Session, user: User, scopes=("registration", "intake")) -> list[DocumentVersion]:
    return required_document_state(db, user, scopes)[1]


def has_current_consents(db: Session, user: User, scopes=("registration", "intake")) -> bool:
    # Operators must be able to publish the first required versions. Their
    # admission is controlled by assigned role and MFA, not participant enrollment.
    if user.role == "admin":
        return True
    configured, versions = required_document_state(db, user, scopes)
    # A required document without a published version must never silently grant access.
    if not configured:
        return False
    required = {version.id for version in versions}
    accepted = set(db.scalars(select(Consent.document_version_id).where(Consent.user_id == user.id)).all())
    return required <= accepted


def require_active(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> User:
    if user.account_status != "active" or (user.role != "admin" and not admitted_profile(user)):
        raise HTTPException(403, "Заполните анкету и дождитесь её одобрения")
    if user.role != "admin" and not has_current_consents(db, user):
        raise HTTPException(403, "Подтвердите актуальные версии обязательных документов")
    return user


def require_admin(user: User = Depends(require_active)) -> User:
    if user.role != "admin":
        raise HTTPException(403, "Доступ разрешён только администратору")
    return user
