from datetime import date, time, timedelta
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
import ipaddress

from pydantic import BaseModel, Field, HttpUrl, field_validator, model_validator


class AvailabilityInput(BaseModel):
    weekday: int = Field(ge=0, le=6)
    start_time: time
    end_time: time
    timezone: str = Field(max_length=80)
    slot_minutes: int = Field(default=30, ge=15, le=120)
    starts_on: date
    ends_on: date | None = None
    horizon_weeks: int = Field(default=8, ge=1, le=12)
    dst_fold: Literal["first", "second"] = "first"

    @field_validator("timezone")
    @classmethod
    def valid_timezone(cls, value):
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError:
            raise ValueError("Укажите часовой пояс IANA") from None
        return value

    @field_validator("start_time", "end_time")
    @classmethod
    def plain_wall_time(cls, value):
        if value.tzinfo is not None or value.second or value.microsecond:
            raise ValueError("Укажите локальное время с точностью до минут")
        return value

    @model_validator(mode="after")
    def valid_interval(self):
        duration = (self.end_time.hour * 60 + self.end_time.minute) - (self.start_time.hour * 60 + self.start_time.minute)
        if duration <= 0 or duration > 12 * 60 or duration % self.slot_minutes:
            raise ValueError("Интервал должен быть в пределах одного дня, до 12 часов и делиться на длительность встречи")
        if self.ends_on and (self.ends_on < self.starts_on or self.ends_on > self.starts_on + timedelta(days=366)):
            raise ValueError("Дата окончания должна быть в пределах года от начала")
        return self


class MeetingURLInput(BaseModel):
    meeting_url: HttpUrl | None = None

    @field_validator("meeting_url")
    @classmethod
    def safe_meeting_url(cls, value):
        if value is None:
            return value
        if value.scheme != "https" or value.username or value.password or not value.host or len(str(value)) > 2048:
            raise ValueError("Используйте публичную HTTPS-ссылку без логина и пароля")
        host = value.host.strip("[]").lower()
        if host in {"localhost", "localhost.localdomain"} or host.endswith((".local", ".localhost")):
            raise ValueError("Локальная ссылка недопустима")
        try:
            address = ipaddress.ip_address(host)
        except ValueError:
            return value
        if not address.is_global:
            raise ValueError("Внутренний адрес недопустим")
        return value


class NoShowInput(BaseModel):
    reason: str = Field(min_length=5, max_length=1000)

    @field_validator("reason", mode="before")
    @classmethod
    def trim_reason(cls, value):
        return value.strip() if isinstance(value, str) else value
