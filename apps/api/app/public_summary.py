"""Small public counts without loading results, feedback or participation history."""
from collections import defaultdict

from sqlalchemy import func, select

from app.auth import document_applies, required_documents_configured
from app.models import Consent, Direction, Document, DocumentVersion, Project, User
from app.profile_state import admitted_profile


def landing_counts(db):
    # One current version per document, including unpublished required documents.
    # Use the same ordering and applicability rules as has_current_consents.
    scopes = ("registration", "intake")
    latest = (select(DocumentVersion.id).where(DocumentVersion.document_id == Document.id)
              .order_by(DocumentVersion.published_at.desc(), DocumentVersion.id.desc())
              .limit(1).correlate(Document).scalar_subquery())
    documents = db.execute(select(Document, latest.label("version_id")).where(
        Document.active.is_(True), Document.scope.in_(scopes))).all()
    current_versions = select(latest).select_from(Document).where(
        Document.active.is_(True), Document.scope.in_(scopes))
    accepted = defaultdict(set)
    for user_id, version_id in db.execute(select(Consent.user_id, Consent.document_version_id).where(
            Consent.document_version_id.in_(current_versions))).yield_per(200):
        accepted[user_id].add(version_id)
    active_directions = set(db.scalars(select(Direction.id).where(Direction.active.is_(True))))
    eligible_ids = set()
    mentors = 0
    for user in db.scalars(select(User).where(User.role.in_(("mentor", "mentee")),
            User.account_status == "active", User.profile_completed.is_(True))).yield_per(100):
        if not admitted_profile(user):
            continue
        applicable = [(document, version) for document, version in documents if document_applies(document, user)]
        required = {version for _, version in applicable if version is not None}
        if not required_documents_configured([document for document, _ in applicable], len(required), user, scopes):
            continue
        if not required <= accepted[user.id]:
            continue
        eligible_ids.add(user.id)
        # Closed/full mentors remain visible in the public mentor catalog.
        if user.role == "mentor" and set(user.direction_ids or []) & active_directions:
            mentors += 1
    # Public projects depend on eligible owners and active directions. Aggregate
    # by owner in SQL, with no pagination or loading descriptions/private fields.
    projects = sum(count for owner_id, count in db.execute(
        select(Project.owner_id, func.count(Project.id)).join(Direction, Direction.id == Project.direction_id)
        .where(Project.visibility_status == "published", Direction.active.is_(True))
        .group_by(Project.owner_id)) if owner_id in eligible_ids)
    return {"mentors": mentors, "participants": len(eligible_ids), "projects": projects}
