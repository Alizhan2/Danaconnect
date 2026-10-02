from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


Stage = Literal["idea", "prototype", "mvp", "growth"]
RejectionReason = Literal["capacity_full", "direction_mismatch", "skills_mismatch", "insufficient_information", "not_a_fit", "project_closed"]


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class ProjectCreate(Input):
    title: str = Field(min_length=3, max_length=220)
    problem: str = Field(min_length=10, max_length=10000)
    description: str = Field(min_length=10, max_length=20000)
    private_details: str = Field(default="", max_length=30000)
    direction_id: str = Field(min_length=1, max_length=36)
    stage: Stage = "idea"
    required_skills: list[str] = Field(default_factory=list, max_length=30)
    capacity: int = Field(default=3, ge=1, le=50)

    @field_validator("required_skills")
    @classmethod
    def skills(cls, values):
        cleaned = [value.strip() for value in values]
        if any(not value or len(value) > 80 for value in cleaned):
            raise ValueError("Каждый навык должен содержать от 1 до 80 символов")
        return list(dict.fromkeys(cleaned))


class ProjectUpdate(Input):
    title: str | None = Field(default=None, min_length=3, max_length=220)
    problem: str | None = Field(default=None, min_length=10, max_length=10000)
    description: str | None = Field(default=None, min_length=10, max_length=20000)
    private_details: str | None = Field(default=None, max_length=30000)
    direction_id: str | None = Field(default=None, min_length=1, max_length=36)
    stage: Stage | None = None
    required_skills: list[str] | None = Field(default=None, max_length=30)
    capacity: int | None = Field(default=None, ge=1, le=50)

    @field_validator("required_skills")
    @classmethod
    def skills(cls, values):
        return ProjectCreate.skills(values) if values is not None else None

    @model_validator(mode="after")
    def non_null_fields(self):
        if not self.model_fields_set or any(getattr(self, key) is None for key in self.model_fields_set):
            raise ValueError("Передайте хотя бы одно изменяемое поле без null")
        return self


class ProjectReview(Input):
    decision: Literal["published", "hidden"]
    reason: str = Field(default="", max_length=2000)

    @model_validator(mode="after")
    def hide_reason(self):
        if self.decision == "hidden" and len(self.reason) < 3:
            raise ValueError("Для скрытия проекта укажите причину")
        return self


class ApplicationCreate(Input):
    project_id: str | None = Field(default=None, min_length=1, max_length=36)
    mentor_id: str = Field(min_length=1, max_length=36)
    motivation: str = Field(min_length=10, max_length=5000)


class ApplicationDecision(Input):
    decision: Literal["accepted", "rejected"]
    reason: RejectionReason | None = None

    @model_validator(mode="after")
    def rejection_reason(self):
        if self.decision == "rejected" and self.reason is None:
            raise ValueError("Выберите причину отклонения заявки")
        if self.decision == "accepted" and self.reason is not None:
            raise ValueError("Для принятой заявки причина отклонения не нужна")
        return self


class MessageCreate(Input):
    body: str = Field(min_length=1, max_length=5000)
