from ipaddress import ip_address
from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

Locale = Literal["ru", "kk", "en"]


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class MaterialInput(Input):
    direction_id: str | None = Field(default=None, min_length=1, max_length=36)
    title_ru: str = Field(min_length=3, max_length=220)
    title_kk: str = Field(default="", max_length=220)
    title_en: str = Field(default="", max_length=220)
    description_ru: str = Field(min_length=10, max_length=10000)
    description_kk: str = Field(default="", max_length=10000)
    description_en: str = Field(default="", max_length=10000)
    url: str = Field(min_length=10, max_length=2048)
    content_language: Locale = "ru"
    kind: Literal["article", "video", "course", "guide"] = "guide"
    active: bool = False

    @field_validator("url")
    @classmethod
    def external_url(cls, value):
        try:
            parsed = urlsplit(value)
            _ = parsed.port
            if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
                raise ValueError()
            hostname = parsed.hostname.lower()
            if hostname == "localhost" or hostname.endswith((".localhost", ".local", ".internal")) or "." not in hostname:
                raise ValueError()
            try:
                if not ip_address(hostname).is_global:
                    raise ValueError()
            except ValueError as error:
                # Invalid IP notation is a DNS hostname; a rejected IP still has dots/colon.
                if hostname.replace(".", "").isdigit() or ":" in hostname:
                    raise ValueError() from error
            if any(char.isspace() for char in value) or "\\" in value or "%" in hostname:
                raise ValueError()
        except ValueError:
            raise ValueError("Укажите публичную HTTPS-ссылку без логина и пароля") from None
        return value

    @model_validator(mode="after")
    def complete_translation(self):
        for locale in ("kk", "en"):
            if bool(getattr(self, "title_" + locale)) != bool(getattr(self, "description_" + locale)):
                raise ValueError("Для перевода заполните название и описание вместе")
        return self


class LeaderboardPreference(Input):
    visible: bool
    alias: str = Field(default="", max_length=60)
    consent_version: str | None = Field(default=None, max_length=40)

    @model_validator(mode="after")
    def alias_required(self):
        if self.visible and len(self.alias) < 2:
            raise ValueError("Для рейтинга выберите отображаемое имя от 2 символов")
        if any(ord(char) < 32 for char in self.alias):
            raise ValueError("Отображаемое имя содержит недопустимые символы")
        return self


class AwardInput(Input):
    user_id: str = Field(min_length=1, max_length=36)
    result_id: str | None = Field(default=None, min_length=1, max_length=36)
    kind: Literal["nomination", "certificate"]
    title_ru: str = Field(min_length=3, max_length=220)
    title_kk: str = Field(default="", max_length=220)
    title_en: str = Field(default="", max_length=220)
    description_ru: str = Field(min_length=10, max_length=5000)
    description_kk: str = Field(default="", max_length=5000)
    description_en: str = Field(default="", max_length=5000)

    @model_validator(mode="after")
    def verified_source(self):
        if self.kind == "certificate" and not self.result_id:
            raise ValueError("Сертификат требует подтверждённого результата")
        for locale in ("kk", "en"):
            if bool(getattr(self, "title_" + locale)) != bool(getattr(self, "description_" + locale)):
                raise ValueError("Для перевода заполните название и описание вместе")
        return self


class RevokeAward(Input):
    reason: str = Field(min_length=5, max_length=2000)
