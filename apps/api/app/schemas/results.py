"""Result lifecycle inputs; counts and verification are always server-owned."""
from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


ExitReason = Literal["goal_achieved", "lack_time", "changed_interests", "mentorship_mismatch", "technical_issue", "personal_circumstances", "other"]


class TrimmedInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class PauseInput(TrimmedInput):
    reason: str = Field(min_length=1, max_length=2000)


class CompleteInput(TrimmedInput):
    status: Literal["completed_successfully", "completed_early"]
    exit_reason: ExitReason
    artifact_url: str | None = Field(default=None, max_length=2000)
    summary: str = Field(default="", max_length=10000)

    @field_validator("artifact_url")
    @classmethod
    def public_http_url(cls, value):
        if not value:
            return None
        try:
            parsed = urlsplit(value)
            valid = parsed.scheme in {"https", "http"} and parsed.hostname and not parsed.username and not parsed.password
            _ = parsed.port
        except ValueError:
            valid = False
        if not valid or any(character.isspace() for character in value):
            raise ValueError("Укажите ссылку HTTP или HTTPS без учётных данных")
        return value

    @model_validator(mode="after")
    def coherent_completion(self):
        if self.status == "completed_successfully":
            if self.exit_reason != "goal_achieved" or not self.artifact_url or not self.summary:
                raise ValueError("Успешное завершение требует достигнутой цели, ссылки на результат и описания")
        elif self.exit_reason == "goal_achieved":
            raise ValueError("Для досрочного выхода выберите причину прекращения участия")
        if self.exit_reason == "other" and not self.summary:
            raise ValueError("Опишите другую причину выхода в поле summary")
        return self


class FeedbackInput(TrimmedInput):
    rating: int = Field(ge=1, le=5, strict=True)
    nps: int | None = Field(default=None, ge=0, le=10, strict=True)
    comment: str = Field(default="", max_length=5000)


class ShowcaseConsentInput(TrimmedInput):
    accepted: bool = Field(strict=True)
