"""Validated concrete occurrences; recurring rules live in schemas/calendar_rules.py."""
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator, model_validator


class SlotCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    starts_at: AwareDatetime
    ends_at: AwareDatetime | None = None
    timezone: str = Field(min_length=1, max_length=80)

    @field_validator("timezone")
    @classmethod
    def valid_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError):
            raise ValueError("Укажите существующий часовой пояс IANA, например Asia/Oral")
        return value

    @model_validator(mode="after")
    def valid_interval(self):
        self.starts_at = self.starts_at.astimezone(timezone.utc)
        self.ends_at = (self.ends_at.astimezone(timezone.utc) if self.ends_at
                        else self.starts_at + timedelta(minutes=30))
        minutes = (self.ends_at - self.starts_at).total_seconds() / 60
        if not 30 <= minutes <= 60:
            raise ValueError("Длительность встречи должна быть от 30 до 60 минут")
        return self


class BookingCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    slot_id: str = Field(min_length=1, max_length=36)
    participation_id: str | None = Field(default=None, min_length=1, max_length=36)
