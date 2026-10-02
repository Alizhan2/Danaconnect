"""Unread counts and caller-only, idempotent receipts for explicitly shown IDs."""
from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import and_, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session

from app.auth import has_current_consents, require_active
from app.database import get_db
from app.models import ConversationMember, Message, User, utcnow
from app.models_engagement import MessageRead
from app.transactions import lock_users


router = APIRouter(tags=["message-engagement"])


class ReadInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    message_ids: list[Annotated[str, Field(min_length=1, max_length=36)]] = Field(min_length=1, max_length=100)

    @field_validator("message_ids")
    @classmethod
    def unique_ids(cls, values):
        if len(set(values)) != len(values):
            raise ValueError("Укажите до 100 уникальных сообщений")
        return values


def unread_summary(db, user_id):
    rows = db.execute(select(Message.conversation_id, func.count(Message.id))
        .join(ConversationMember, and_(ConversationMember.conversation_id == Message.conversation_id, ConversationMember.user_id == user_id))
        .outerjoin(MessageRead, and_(MessageRead.message_id == Message.id, MessageRead.user_id == user_id))
        .where(Message.sender_id != user_id, MessageRead.id.is_(None))
        .group_by(Message.conversation_id).order_by(Message.conversation_id)).all()
    conversations = [{"id": identifier, "unread_count": count} for identifier, count in rows]
    return {"total_unread": sum(item["unread_count"] for item in conversations), "conversations": conversations}


@router.get("/messages/unread-summary")
def summary(user: User = Depends(require_active), db: Session = Depends(get_db)):
    return unread_summary(db, user.id)


@router.post("/conversations/{conversation_id}/read")
def read_messages(conversation_id: str, payload: ReadInput, user: User = Depends(require_active), db: Session = Depends(get_db)):
    identifier = user.id
    user = lock_users(db, [identifier])[identifier]
    if user.account_status != "active" or (user.role != "admin" and not user.profile_completed) or not has_current_consents(db, user):
        raise HTTPException(403, "Для сообщений нужны одобренная анкета и актуальные документы")
    membership = db.scalar(select(ConversationMember.id).where(ConversationMember.conversation_id == conversation_id, ConversationMember.user_id == identifier))
    if not membership:
        raise HTTPException(404, "Диалог не найден")
    rows = db.execute(select(Message.id, Message.sender_id).where(Message.conversation_id == conversation_id, Message.id.in_(payload.message_ids))).all()
    # All-or-nothing: neither unknown IDs nor another conversation's messages
    # can widen this receipt set, and the caller cannot write another reader.
    if {row.id for row in rows} != set(payload.message_ids):
        raise HTTPException(404, "Сообщения не найдены в этом диалоге")
    if any(row.sender_id == identifier for row in rows):
        raise HTTPException(422, "Отметить прочитанными можно только входящие сообщения")
    insert = sqlite_insert if db.get_bind().dialect.name == "sqlite" else pg_insert
    now = utcnow()
    try:
        db.execute(insert(MessageRead).values([{"id": str(uuid4()), "user_id": identifier, "message_id": row.id, "read_at": now} for row in rows]).on_conflict_do_nothing(index_elements=["user_id", "message_id"]))
        db.commit()
    except (IntegrityError, OperationalError):
        db.rollback()
        raise HTTPException(409, "Статус сообщений обновляется. Повторите позже") from None
    return {"conversation_id": conversation_id, "read_message_ids": payload.message_ids, "summary": unread_summary(db, identifier)}
