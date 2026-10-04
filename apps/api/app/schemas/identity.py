from datetime import date
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from email_validator import EmailNotValidError, validate_email
from pydantic import BaseModel, Field, HttpUrl, StrictBool, field_validator

from app.config import settings


class RequestCode(BaseModel):
    email: str = Field(max_length=254)
    locale: Literal["ru", "kk", "en"] | None = None

    @field_validator("email")
    @classmethod
    def valid_email(cls, value):
        try:
            return validate_email(value.strip(), check_deliverability=False, test_environment=settings.environment != "production").normalized
        except EmailNotValidError:
            raise ValueError("Укажите корректный email")


class VerifyCode(BaseModel):
    challenge_id: str = Field(min_length=1, max_length=64)
    code: str = Field(pattern=r"^\d{6}$")


class MFAVerify(BaseModel):
    mfa_challenge_id: str = Field(min_length=32, max_length=128)
    code: str = Field(pattern=r"^\d{6}$")


class ConsentInput(BaseModel):
    content_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    content_locale: Literal["ru", "kk", "en"]


class ProfileInput(BaseModel):
    full_name: str = Field(min_length=2, max_length=160)
    role: Literal["mentee", "mentor"] | None = None
    timezone: str = "Asia/Almaty"
    city: str = Field(min_length=1, max_length=120)
    organization: str = Field(default="", max_length=300)
    phone: str | None = Field(default=None, max_length=40)
    birth_date: date | None = None
    bio: str = Field(min_length=10, max_length=5000)
    expertise: str = Field(default="", max_length=3000)
    evidence_urls: list[HttpUrl] = Field(default_factory=list, max_length=10)
    direction_ids: list[str] = Field(min_length=1, max_length=10)
    capacity: int = Field(default=3, ge=0, le=50)
    preferred_locale: Literal["ru", "kk", "en"] | None = None
    mentor_commitment: StrictBool = False

    @field_validator("timezone")
    @classmethod
    def valid_timezone(cls, value):
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError:
            raise ValueError("Укажите часовой пояс IANA")
        return value

    @field_validator("full_name", "city", "bio", "expertise", "organization", "phone", mode="before")
    @classmethod
    def trim(cls, value):
        return value.strip() if isinstance(value, str) else value

    @field_validator("phone")
    @classmethod
    def optional_phone(cls, value):
        if value and any(ord(char) < 32 for char in value):
            raise ValueError("Укажите телефон без управляющих символов")
        return value or None

    @field_validator("birth_date")
    @classmethod
    def not_future(cls, value):
        if value and value > date.today():
            raise ValueError("Дата рождения не может быть в будущем")
        return value


class IntakeInput(BaseModel):
    intake_open: bool
    capacity: int | None = Field(default=None, ge=0, le=50)


class ReviewInput(BaseModel):
    decision: Literal["approved", "changes_requested"]
    reason: str = Field(default="", max_length=2000)


class DirectionInput(BaseModel):
    slug: str = Field(pattern=r"^[a-z][a-z0-9-]{1,59}$")
    name_ru: str = Field(min_length=1, max_length=160)
    name_kk: str = Field(min_length=1, max_length=160)
    name_en: str = Field(min_length=1, max_length=160)
    description_ru: str = Field(default="", max_length=3000)
    active: bool = True


class DirectionUpdate(BaseModel):
    name_ru: str | None = Field(default=None, min_length=1, max_length=160)
    name_kk: str | None = Field(default=None, min_length=1, max_length=160)
    name_en: str | None = Field(default=None, min_length=1, max_length=160)
    description_ru: str | None = Field(default=None, max_length=3000)
    active: bool | None = None
