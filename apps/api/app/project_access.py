"""Shared live eligibility for public project cards and discussion routes."""
from app.auth import has_current_consents
from app.models import Direction, User
from app.profile_state import admitted_profile


def project_is_public(db, project, *, owner=None, direction=None):
    owner = owner or db.get(User, project.owner_id)
    direction = direction or db.get(Direction, project.direction_id)
    return bool(project.visibility_status == "published" and direction and direction.active
                and owner and owner.role in {"mentor", "mentee"} and owner.account_status == "active"
                and admitted_profile(owner) and has_current_consents(db, owner))
