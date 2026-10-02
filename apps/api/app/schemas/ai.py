from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class ConsentInput(Input):
    consent: Literal[True]
    locale: Literal["ru", "kk", "en"] = "ru"


class StructureInput(ConsentInput):
    text: str = Field(min_length=10, max_length=6000)
    purpose: Literal["project", "profile", "goal"] = "project"


class RecommendationInput(ConsentInput):
    direction_id: str = Field(min_length=1, max_length=36)
    goal: str = Field(min_length=10, max_length=2500)
    skills: list[str] = Field(default_factory=list, max_length=10)

    @field_validator("skills")
    @classmethod
    def bounded_skills(cls, values):
        if any(not item or len(item) > 80 for item in values):
            raise ValueError("Укажите до 10 навыков длиной до 80 символов")
        return list(dict.fromkeys(values))


class PreferenceInput(Input):
    allow_admin_review: bool


class ReviewDecision(Input):
    decision: Literal["approved", "dismissed", "overridden"]
    reason: str = Field(min_length=5, max_length=2000)
    override_summary: str | None = Field(default=None, max_length=3000)


class StructureDraft(Input):
    title: str = Field(max_length=220)
    problem: str = Field(max_length=2000)
    description: str = Field(max_length=6000)
    goal: str = Field(max_length=1000)
    steps: list[str] = Field(max_length=8)
    required_skills: list[str] = Field(max_length=10)
    questions: list[str] = Field(max_length=8)


class ProfileReview(Input):
    completeness_score: int = Field(ge=0, le=100)
    summary: str = Field(max_length=1500)
    strengths: list[str] = Field(max_length=6)
    missing_information: list[str] = Field(max_length=6)
    questions: list[str] = Field(max_length=6)
    recommendation: Literal["needs_human_review"]


class MentorExplanation(Input):
    candidate_id: str = Field(min_length=1, max_length=36)
    reason: str = Field(max_length=800)
    matching_skills: list[str] = Field(max_length=6)


class MentorRecommendations(Input):
    recommendations: list[MentorExplanation] = Field(max_length=5)
    questions: list[str] = Field(max_length=5)
