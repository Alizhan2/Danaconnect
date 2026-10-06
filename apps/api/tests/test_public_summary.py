"""Landing metrics match public admission without analytics or pagination limits."""
from datetime import timedelta

import pytest
from sqlalchemy import delete, event
from sqlalchemy.exc import OperationalError

from app.config import settings
from app.models import AuditEvent, Consent, Direction, Document, DocumentVersion, Project, User, utcnow


def summary(api):
    response = api.call("GET", "/public-summary")
    assert response.status_code == 200, response.text
    return response.json()


def test_anonymous_counts_unique_people_closed_mentors_and_no_demo_fixtures(integrated_api):
    api = integrated_api
    with api.factory() as db:
        mentor = db.get(User, api.ids["mentor"])
        mentor.intake_open, mentor.capacity = False, 0
        db.commit()
    assert summary(api) == {"mentors": 1, "participants": 3, "projects": 0, "demo_mode": False}
    assert len(api.call("GET", "/mentors").json()) == 1


@pytest.mark.parametrize("change", ["suspended", "unapproved", "incomplete", "consent"])
def test_ineligible_people_not_counted(integrated_api, change):
    api = integrated_api
    with api.factory() as db:
        mentor = db.get(User, api.ids["mentor"])
        if change == "suspended":
            mentor.account_status = "suspended"
        elif change == "unapproved":
            mentor.profile_completed = False
        elif change == "incomplete":
            mentor.organization = ""
        else:
            db.execute(delete(Consent).where(Consent.user_id == mentor.id))
        db.commit()
    assert summary(api) == {"mentors": 0, "participants": 2, "projects": 0, "demo_mode": False}
    assert api.call("GET", "/mentors").json() == []


def test_projects_match_catalog_and_count_beyond_first_page(integrated_api):
    api = integrated_api
    with api.factory() as db:
        inactive = Direction(slug="inactive", name_ru="Inactive", active=False)
        db.add(inactive)
        db.flush()
        # Both mentee ideas and assigned projects are public, including full ones.
        for number in range(105):
            db.add(Project(owner_id=api.ids["mentee"], mentor_id=api.ids["mentor"] if number % 2 else None,
                direction_id=api.ids["direction"], title=f"Public {number}", problem="Public problem",
                description="Public description", visibility_status="published", capacity=1))
        for status, direction, owner in [("pending", api.ids["direction"], "mentee"),
                ("published", inactive.id, "mentee"), ("published", api.ids["direction"], "admin"),
                ("published", api.ids["direction"], "stranger")]:
            db.add(Project(owner_id=api.ids[owner], direction_id=direction, title="Hidden",
                problem="Hidden", description="Hidden", visibility_status=status))
        db.get(User, api.ids["stranger"]).bio = "short"
        db.commit()
    assert summary(api)["projects"] == 105
    first = api.call("GET", "/projects?limit=100").json()
    second = api.call("GET", "/projects?limit=100&offset=100").json()
    assert len(first) == 100 and len(second) == 5
    assert all(item["title"].startswith("Public ") for item in first + second)
    with api.factory() as db:
        db.execute(delete(Consent).where(Consent.user_id == api.ids["mentee"]))
        db.commit()
    assert summary(api)["projects"] == 0
    assert api.call("GET", "/projects").json() == []


def test_current_versions_role_direction_applicability_and_unpublished_documents(integrated_api):
    api = integrated_api
    with api.factory() as db:
        other_direction = Direction(slug="other", name_ru="Other")
        db.add(other_direction)
        db.flush()
        db.add_all([
            Document(slug="other-direction", title="Unrelated", scope="intake", direction_id=other_direction.id),
            Document(slug="admin-only", title="Unrelated", scope="registration", required_roles=["admin"]),
            Document(slug="private-only", title="Unrelated", scope="private_project"),
        ])
        document = Document(slug="mentor-intake", title="Mentor only", scope="intake",
            required_roles=["mentor"], direction_id=api.ids["direction"])
        db.add(document)
        db.commit()
        document_id = document.id
    assert summary(api)["participants"] == 2  # no published version fails closed
    with api.factory() as db:
        old = DocumentVersion(document_id=document_id, version="1", content="Terms", content_hash="a" * 64)
        db.add(old)
        db.flush()
        db.add(Consent(user_id=api.ids["mentor"], document_version_id=old.id))
        db.commit()
    assert summary(api)["mentors"] == 1
    with api.factory() as db:
        newest = DocumentVersion(document_id=document_id, version="2", content="Updated", content_hash="b" * 64,
            published_at=utcnow() + timedelta(seconds=1))
        db.add(newest)
        db.commit()
    assert summary(api)["mentors"] == 0
    with api.factory() as db:
        db.get(Document, document_id).active = False
        db.commit()
    assert summary(api)["mentors"] == 1


def test_no_active_direction_hides_mentors_and_projects_but_not_admitted_participants(integrated_api):
    api = integrated_api
    with api.factory() as db:
        db.get(Direction, api.ids["direction"]).active = False
        db.commit()
    assert summary(api) == {"mentors": 0, "participants": 3, "projects": 0, "demo_mode": False}
    assert api.call("GET", "/mentors").json() == []


def test_production_missing_registration_terms_fails_closed(integrated_api, monkeypatch):
    api = integrated_api
    with api.factory() as db:
        db.get(Document, api.ids["document"]).active = False
        db.commit()
    monkeypatch.setattr(settings, "environment", "production")
    assert summary(api) == {"mentors": 0, "participants": 0, "projects": 0, "demo_mode": False}


def test_persisted_demo_marker_survives_toggle(integrated_api):
    api = integrated_api
    with api.factory() as db:
        db.add(AuditEvent(action="demo_seed", entity_type="system", entity_id="test"))
        db.commit()
    assert summary(api)["demo_mode"] is True


def test_small_read_only_query_budget_and_no_analytics(integrated_api, monkeypatch):
    api = integrated_api
    def reject_analytics(*args):
        raise AssertionError("The landing page must not calculate historical analytics")
    monkeypatch.setattr("app.routers.results._analytics", reject_analytics)
    engine = api.factory.kw["bind"]
    statements = []
    def record(connection, cursor, statement, parameters, context, executemany):
        statements.append(statement)
    event.listen(engine, "before_cursor_execute", record)
    try:
        assert summary(api)["participants"] == 3
    finally:
        event.remove(engine, "before_cursor_execute", record)
    assert len(statements) == 6
    assert all(statement.lstrip().upper().startswith("SELECT") for statement in statements)
    assert not any(table in statement.lower() for statement in statements for table in ("participations", "feedback", "results"))


def test_database_failure_not_converted_to_false_zero(integrated_api, monkeypatch):
    def fail(db):
        raise OperationalError("Synthetic failure", {}, Exception("unavailable"))
    monkeypatch.setattr("app.public_summary.landing_counts", fail)
    response = integrated_api.call("GET", "/public-summary")
    assert response.status_code == 500
    assert "mentors" not in response.json()
