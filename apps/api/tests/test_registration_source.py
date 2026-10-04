"""Source registration parity using isolated synthetic people; no provider calls."""
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from alembic import command
from alembic.config import Config
import pytest
from sqlalchemy import create_engine, inspect, select

from app.config import settings
from app.models import AuditEvent, Direction, User, utcnow
from app.models_delivery import OAuthState
from app.profile_state import MENTOR_COMMITMENT_VERSION
from app.routers import identity


def test_registration_source_mentee_organization_phone_optional_and_commitment_cleared(integrated_api):
    api = integrated_api
    api.login("source-mentee", "source-mentee@example.test")
    result = api.call("PUT", "/me/profile", "source-mentee", json=api.profile(
        organization="  Synthetic university  ", phone="  ", mentor_commitment=True))
    assert result.status_code == 200
    account = result.json()
    assert account["profile_completed"] is True
    assert account["organization"] == "Synthetic university" and account["phone"] is None
    assert account["mentor_commitment"] is False and account["mentor_commitment_accepted_at"] is None
    cleared = api.call("PUT", "/me/profile", "source-mentee", json=api.profile())
    assert cleared.json()["organization"] == "" and cleared.json()["profile_completed"] is True


@pytest.mark.parametrize("changes", [
    {"organization": "  "}, {"phone": "  "}, {"mentor_commitment": False}, {"evidence_urls": []},
])
def test_registration_source_mentor_missing_required_fields_only_saves_incomplete_draft(integrated_api, changes):
    api = integrated_api
    api.login("source-mentor", "source-mentor@example.test")
    saved = api.call("PUT", "/me/profile", "source-mentor", json=api.profile("mentor", **changes))
    assert saved.status_code == 200, saved.text
    assert saved.json()["profile_completed"] is False and saved.json()["account_status"] == "draft"
    assert api.call("POST", "/me/submit-registration", "source-mentor").status_code == 409


@pytest.mark.parametrize("changes", [
    {"organization": "x" * 301}, {"phone": "x" * 41}, {"phone": "123\n456"},
    {"mentor_commitment": "true"}, {"mentor_commitment": 1}, {"mentor_commitment": None},
])
def test_registration_source_bounds_strict_checkbox_and_phone_controls(integrated_api, changes):
    api = integrated_api
    assert api.call("PUT", "/me/profile", "mentor", json=api.profile("mentor", **changes)).status_code == 422


def test_registration_source_explicit_commitment_server_timestamp_preserved_and_withdrawn(integrated_api):
    api = integrated_api
    api.login("source-mentor", "source-mentor@example.test")
    payload = api.profile("mentor", organization="  Synthetic workplace  ", phone="  +7 700 000 00 00  ",
        mentor_commitment_accepted_at="1900-01-01T00:00:00Z")
    before = utcnow()
    first = api.call("PUT", "/me/profile", "source-mentor", json=payload)
    assert first.status_code == 200 and first.json()["profile_completed"] is True
    assert first.json()["phone"] == "+7 700 000 00 00" and first.json()["organization"] == "Synthetic workplace"
    accepted = first.json()["mentor_commitment_accepted_at"]
    assert accepted and not accepted.startswith("1900")
    repeated = api.call("PUT", "/me/profile", "source-mentor", json=payload)
    assert repeated.json()["mentor_commitment_accepted_at"] == accepted
    with api.factory() as db:
        user = db.get(User, api.ids["source-mentor"])
        assert user.mentor_commitment_accepted_at >= before
        events = list(db.scalars(select(AuditEvent).where(AuditEvent.action == "mentor_commitment.accepted", AuditEvent.actor_id == user.id)))
        assert len(events) == 1 and events[0].detail == {"version": MENTOR_COMMITMENT_VERSION}
    exported = api.call("GET", "/me/data-export", "source-mentor").json()["account"]
    assert exported["organization"] == "Synthetic workplace" and exported["mentor_commitment_accepted_at"] == accepted
    withdrawn = api.call("PUT", "/me/profile", "source-mentor", json={**payload, "mentor_commitment": False})
    assert withdrawn.json()["mentor_commitment_accepted_at"] is None and withdrawn.json()["profile_completed"] is False
    accepted_again = api.call("PUT", "/me/profile", "source-mentor", json=payload)
    assert accepted_again.json()["mentor_commitment_accepted_at"] != accepted


@pytest.mark.parametrize("attribute, value", [
    ("organization", ""), ("phone", None), ("mentor_commitment", False), ("mentor_commitment_accepted_at", None),
])
def test_registration_source_stale_active_flag_never_grants_access_or_public_listing(integrated_api, attribute, value):
    api = integrated_api
    with api.factory() as db:
        user = db.get(User, api.ids["mentor"])
        setattr(user, attribute, value)
        assert user.profile_completed is True
        db.commit()
    assert api.call("GET", "/auth/me", "mentor").json()["profile_completed"] is False
    assert api.call("GET", "/participations", "mentor").status_code == 403
    assert api.call("PATCH", "/me/intake", "mentor", json={"intake_open": True}).status_code == 403
    assert api.call("GET", f"/mentors/{api.ids['mentor']}").status_code == 404
    assert api.ids["mentor"] not in {row["id"] for row in api.call("GET", "/mentors").json()}
    guide = api.call("GET", "/me/next-steps", "mentor")
    assert guide.status_code == 200 and guide.json()["profile_completed"] is False
    assert any(step["id"] == "profile" for step in guide.json()["steps"])
    with api.factory() as db:
        assert db.get(User, api.ids["mentor"]).account_status == "active"


def test_registration_source_mandatory_fields_remain_private(integrated_api):
    api = integrated_api
    for path in ("/mentors", f"/mentors/{api.ids['mentor']}"):
        result = api.call("GET", path)
        assert result.status_code == 200
        assert "PRIVATE-ORGANIZATION" not in result.text
        items = result.json() if isinstance(result.json(), list) else [result.json()]
        for item in items:
            assert not {"organization", "phone", "mentor_commitment", "mentor_commitment_accepted_at"} & item.keys()


def test_registration_source_public_project_owner_live_admission_before_pagination(integrated_api):
    from app.models import Project
    from datetime import timedelta
    api = integrated_api
    with api.factory() as db:
        mentor = db.get(User, api.ids["mentor"])
        mentor.organization = ""
        mentor.profile_completed = True
        hidden = Project(owner_id=mentor.id, mentor_id=mentor.id, direction_id=api.ids["direction"],
            title="Synthetic hidden legacy card", problem="Synthetic problem", description="Synthetic description",
            visibility_status="published", created_at=utcnow())
        first = Project(owner_id=api.ids["mentee"], direction_id=api.ids["direction"],
            title="Synthetic valid first", problem="Synthetic problem", description="Synthetic description",
            visibility_status="published", created_at=utcnow()-timedelta(days=1))
        second = Project(owner_id=api.ids["mentee"], direction_id=api.ids["direction"],
            title="Synthetic valid second", problem="Synthetic problem", description="Synthetic description",
            visibility_status="published", created_at=utcnow()-timedelta(days=2))
        db.add_all([hidden, first, second]); db.commit()
        hidden_id, first_id, second_id = hidden.id, first.id, second.id
    assert [row["id"] for row in api.call("GET", "/projects", params={"limit": 1}).json()] == [first_id]
    assert [row["id"] for row in api.call("GET", "/projects", params={"limit": 1, "offset": 1}).json()] == [second_id]
    assert api.call("GET", f"/projects/{hidden_id}").status_code == 404
    assert api.call("GET", f"/projects/{hidden_id}/comments", "mentee").status_code == 404
    # The owner can still inspect their safe public fields to repair the profile.
    assert api.call("GET", f"/projects/{hidden_id}", "mentor").status_code == 200
    assert api.call("GET", f"/projects/{hidden_id}/private", "mentor").status_code == 403


def test_registration_source_incomplete_legacy_comment_author_uses_generic_name(integrated_api):
    from app.models import Project
    from app.models_collaboration import ProjectComment
    from app.routers.collaboration import comment_view
    api = integrated_api
    with api.factory() as db:
        mentor = db.get(User, api.ids["mentor"])
        mentor.organization = ""
        project = Project(owner_id=api.ids["mentee"], direction_id=api.ids["direction"], title="Synthetic discussion",
            problem="Synthetic problem", description="Synthetic description", visibility_status="published")
        db.add(project); db.flush()
        comment = ProjectComment(project_id=project.id, author_id=mentor.id, body="Synthetic comment", scope="public", status="visible")
        db.add(comment); db.flush()
        assert comment_view(db, comment)["author_name"] == "Участник"


def test_registration_source_changed_workplace_requires_review_and_closes_intake(integrated_api):
    api = integrated_api
    with api.factory() as db:
        user = db.get(User, api.ids["mentor"])
        payload = api.profile("mentor", full_name=user.full_name, organization=user.organization,
            phone=user.phone, evidence_urls=user.evidence_urls)
    unchanged = api.call("PUT", "/me/profile", "mentor", json=payload)
    assert unchanged.json()["account_status"] == "active" and unchanged.json()["intake_open"] is True
    changed = api.call("PUT", "/me/profile", "mentor", json={**payload, "organization": "New synthetic workplace"})
    assert changed.status_code == 200 and changed.json()["profile_completed"] is True
    assert changed.json()["account_status"] == "draft" and changed.json()["intake_open"] is False


def test_registration_source_review_and_reactivation_require_live_commitment(integrated_api):
    api = integrated_api
    with api.factory() as db:
        user = db.get(User, api.ids["mentor"])
        user.account_status = "pending"
        user.mentor_commitment_accepted_at = None
        db.commit()
    result = api.call("POST", f"/admin/registrations/{api.ids['mentor']}/review", "admin", json={"decision": "approved"})
    assert result.status_code == 409
    with api.factory() as db:
        from app.models import RegistrationReview
        db.get(User, api.ids["mentor"]).account_status = "suspended"
        db.add(RegistrationReview(user_id=api.ids["mentor"], admin_id=api.ids["admin"], decision="approved", reason="Synthetic earlier review"))
        db.commit()
    restored = api.call("PATCH", f"/admin/users/{api.ids['mentor']}/status", "admin", json={"status": "active", "reason": "Synthetic reactivation"})
    assert restored.status_code == 409


@pytest.mark.parametrize("module", ["bookings", "projects", "results", "collaboration"])
def test_registration_source_domain_helpers_recheck_live_profile_after_lock(integrated_api, module):
    from fastapi import HTTPException
    from app.routers import bookings, collaboration, projects, results
    with integrated_api.factory() as db:
        user = db.get(User, integrated_api.ids["mentor"])
        user.mentor_commitment = False
        user.mentor_commitment_accepted_at = None
        assert user.profile_completed is True
        with pytest.raises(HTTPException) as error:
            if module == "bookings":
                bookings._active(db, user, "mentor")
            elif module == "projects":
                projects.ensure_user_enrolled(db, user, "mentor")
            elif module == "results":
                results._active(db, user)
            else:
                collaboration.private_permission(db, None, user)
        assert error.value.status_code == 403


def test_registration_source_role_changes_never_reuse_previous_mentor_affirmation(integrated_api):
    api = integrated_api
    for role in ("mentee", "mentor"):
        result = api.call("PATCH", f"/admin/users/{api.ids['mentor']}/role", "admin", json={"role": role, "reason": "Synthetic role correction"})
        assert result.status_code == 200
        assert result.json()["mentor_commitment"] is False and result.json()["mentor_commitment_accepted_at"] is None


def test_registration_source_private_queue_role_direction_filters_before_pagination(integrated_api):
    api = integrated_api
    with api.factory() as db:
        extra = Direction(slug="synthetic-other", name_ru="Synthetic other")
        db.add(extra); db.flush()
        for key in ("mentor", "mentee", "stranger"):
            db.get(User, api.ids[key]).account_status = "pending"
        db.get(User, api.ids["stranger"]).direction_ids = [extra.id]
        db.commit(); other_id = extra.id
    mentors = api.call("GET", "/admin/registrations", "admin", params={"role": "mentor", "limit": 1}).json()
    assert [row["id"] for row in mentors] == [api.ids["mentor"]]
    mentees = api.call("GET", "/admin/registrations", "admin", params={"role": "mentee", "direction_id": api.ids["direction"], "limit": 1}).json()
    assert [row["id"] for row in mentees] == [api.ids["mentee"]]
    other = api.call("GET", "/admin/registrations", "admin", params={"direction_id": other_id}).json()
    assert [row["id"] for row in other] == [api.ids["stranger"]]
    assert api.call("GET", "/admin/registrations", "admin", params={"role": "admin"}).status_code == 422
    assert api.call("GET", "/admin/registrations", "admin", params={"direction_id": "x" * 37}).status_code == 422
    assert api.call("GET", "/admin/registrations", "mentee").status_code == 403


def test_registration_source_complete_mentor_cannot_bypass_unpublished_production_documents(integrated_api, monkeypatch):
    api = integrated_api
    api.login("source-mentor", "source-mentor@example.test")
    assert api.call("PUT", "/me/profile", "source-mentor", json=api.profile("mentor")).json()["profile_completed"] is True
    with api.factory() as db:
        from app.models import Document
        db.get(Document, api.ids["document"]).active = False
        db.commit()
    monkeypatch.setattr(settings, "environment", "production")
    assert api.call("POST", "/me/submit-registration", "source-mentor").status_code == 503


@pytest.mark.parametrize("value", ["https://evil.example/", "//evil.example/", "/%2F%2Fevil.example/", "/%252F%252Fevil.example/", "/\\evil.example/", "/%5Cevil.example/", "/api/v1/auth/me", "/admin/users", "/login", "/onboarding", "/foo/../admin", "/foo%0Abar"])
def test_registration_source_google_return_paths_never_leave_participant_routes(value):
    assert identity.safe_participant_return(value) == "/dashboard"


def test_registration_source_google_handoff_keeps_hint_only_and_safe_destination(integrated_api, monkeypatch):
    api = integrated_api
    monkeypatch.setattr(settings, "google_client_id", "isolated-client-id")
    monkeypatch.setattr(settings, "google_client_secret", "isolated-client-secret")
    monkeypatch.setattr(settings, "google_redirect_uri", "http://localhost:8000/api/v1/auth/google/callback")
    requested = api.call("GET", "/auth/google/start", params={"role": "mentor", "locale": "kk", "return_to": "/catalog?direction=synthetic#mentors"})
    assert requested.status_code == 200
    state = parse_qs(urlsplit(requested.json()["authorization_url"]).query)["state"][0]
    with api.factory() as db:
        row = db.scalar(select(OAuthState))
        assert row.registration_role == "mentor" and row.return_to == "/catalog?direction=synthetic#mentors"
    monkeypatch.setattr(identity.httpx, "post", lambda *a, **k: type("SyntheticToken", (), {"status_code": 200, "json": lambda self: {"id_token": "synthetic-id-token"}})())
    monkeypatch.setattr(identity, "verify_google_id_token", lambda *a: {"email": "source-google@example.test", "sub": "synthetic-source-google"})
    result = api.client().get("/api/v1/auth/google/callback", params={"state": state, "code": "synthetic-code", "role": "admin", "return_to": "https://evil.example/"}, follow_redirects=False)
    assert result.status_code == 303
    location = urlsplit(result.headers["location"])
    assert location.path == "/onboarding"
    assert parse_qs(location.query) == {"role": ["mentor"], "returnTo": ["/catalog?direction=synthetic#mentors"]}
    current = api.call("GET", "/auth/me").json()
    assert current["role"] == "unchosen" and current["mentor_commitment"] is False
    assert api.call("GET", "/auth/google/start", params={"role": "admin"}).status_code == 422


def test_registration_source_migration_additive_no_fabricated_acceptance(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "database_url", "sqlite:///" + (tmp_path / "registration-migration.db").as_posix())
    root = Path(__file__).resolve().parents[1]
    config = Config(str(root / "alembic.ini")); config.set_main_option("script_location", str(root / "migrations"))
    command.upgrade(config, "52d790adb0ae")
    engine = create_engine(settings.database_url)
    with engine.begin() as connection:
        connection.exec_driver_sql("INSERT INTO users (id,email,full_name,role,account_status,intake_open,timezone,preferred_locale,city,bio,expertise,evidence_urls,direction_ids,capacity,profile_completed,created_at) VALUES ('synthetic-legacy','legacy@example.test','Synthetic legacy','mentor','active',1,'Asia/Oral','ru','Synthetic city','Synthetic biography','Synthetic expertise','[]','[]',3,1,CURRENT_TIMESTAMP)")
    command.upgrade(config, "head")
    with engine.connect() as connection:
        row = connection.exec_driver_sql("SELECT role,account_status,intake_open,profile_completed,organization,mentor_commitment,mentor_commitment_accepted_at FROM users WHERE id='synthetic-legacy'").one()
        assert row == ("mentor", "active", 1, 1, "", 0, None)
    assert {"registration_role", "return_to"} <= {column["name"] for column in inspect(engine).get_columns("oauth_states")}
    command.check(config)
    command.downgrade(config, "52d790adb0ae")
    command.upgrade(config, "head")
    with engine.connect() as connection:
        assert connection.exec_driver_sql("SELECT mentor_commitment,mentor_commitment_accepted_at FROM users WHERE id='synthetic-legacy'").one() == (0, None)
    engine.dispose()
