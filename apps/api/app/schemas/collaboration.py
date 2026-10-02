from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator
from app.schemas.identity import RequestCode


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class CommentInput(Input):
    body: str = Field(min_length=1, max_length=5000)
    scope: Literal["public", "team"] = "team"


class CommentReview(Input):
    decision: Literal["visible", "hidden"]
    reason: str = Field(min_length=3, max_length=2000)


class InvitationInput(Input):
    email: str = Field(max_length=254)
    expires_in_days: int = Field(default=7, ge=1, le=14)

    @field_validator("email")
    @classmethod
    def valid_email(cls, value):
        return RequestCode.valid_email(value).lower()


class InvitationDecision(Input):
    decision: Literal["accepted", "declined"]


class TeamRemovalInput(Input):
    reason: str = Field(min_length=3, max_length=2000)
