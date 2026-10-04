"""Focused domain regression checks on an isolated database, including races."""
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from uuid import uuid4

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.orm import sessionmaker

from app.auth import get_current_user
from app.database import get_db
from app.models import Application, AuditEvent, Base, Consent, Conversation, ConversationMember, Direction, Document, DocumentVersion, Notification, Participation, Project, ProjectMember, User, utcnow
from app.routers.projects import router


@pytest.fixture
def project_api(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'projects.db'}", connect_args={"check_same_thread": False, "timeout": 15})

    @event.listens_for(engine, "connect")
    def enforce_foreign_keys(connection, _):
        connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    identifiers = {}
    with factory() as db:
        direction = Direction(id=str(uuid4()), slug="ai", name_ru="ИИ", name_kk="ЖИ", name_en="AI")
        db.add(direction)
        db.flush()
        identifiers["direction"] = direction.id
        for key, role in (("mentor", "mentor"), ("mentor2", "mentor"), ("mentee", "mentee"), ("mentee2", "mentee"), ("stranger", "mentee"), ("admin", "admin")):
            user = User(id=str(uuid4()), email=f"{key}@example.test", full_name=key, role=role, account_status="active", profile_completed=True, intake_open=True, capacity=1, direction_ids=[direction.id], city="Synthetic city", birth_date=date(2000, 1, 1), bio="Synthetic project biography", expertise="Synthetic mentoring expertise", evidence_urls=["https://example.test/synthetic"], organization="Synthetic workplace", phone="+7 700 000 00 00", mentor_commitment=role == "mentor", mentor_commitment_accepted_at=utcnow() if role == "mentor" else None)
            db.add(user)
            identifiers[key] = user.id
        db.flush()
        project = Project(id=str(uuid4()), owner_id=identifiers["mentor"], mentor_id=identifiers["mentor"], direction_id=direction.id, title="Sample project", problem="Meaningful project problem", description="Public project description", private_details="SECRET NEVER PUBLIC", capacity=2, visibility_status="published")
        db.add(project)
        identifiers["project"] = project.id
        document = Document(id=str(uuid4()), slug="nda", title="NDA", scope="private_project", required_roles=["mentor"], active=True)
        db.add(document)
        db.flush()
        version = DocumentVersion(id=str(uuid4()), document_id=document.id, version="1", content="NDA sample", content_hash="a" * 64)
        db.add(version)
        identifiers["nda"] = version.id
        identifiers["nda_doc"] = document.id
        db.commit()
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")

    def isolated_db():
        with factory() as db:
            yield db

    def fixture_user(request: Request):
        with factory() as db:
            return db.get(User, identifiers[request.headers.get("x-user", "mentee")])

    app.dependency_overrides[get_db] = isolated_db
    app.dependency_overrides[get_current_user] = fixture_user
    with TestClient(app) as client:
        yield client, factory, identifiers
    engine.dispose()


def call(client, method, path, who="mentee", **kwargs):
    return client.request(method, "/api/v1" + path, headers={"x-user": who}, **kwargs)


def apply(client, ids, who="mentee", **changes):
    payload = {"project_id": ids["project"], "mentor_id": ids["mentor"], "motivation": "I want to work on this project"}
    payload.update(changes)
    return call(client, "POST", "/applications", who, json=payload)


def decide(client, application_id, who="mentor", **changes):
    return call(client, "POST", f"/applications/{application_id}/decision", who, json={"decision": "accepted", **changes})


def test_public_project_privacy_and_membership(project_api):
    client, factory, ids = project_api
    for path in ("/projects", f"/projects/{ids['project']}", "/projects/mine", "/admin/projects"):
        response = call(client, "GET", path, "admin" if path == "/admin/projects" else "mentor")
        assert response.status_code == 200
        assert "private_details" not in response.text
        assert "SECRET" not in response.text
    assert call(client, "GET", f"/projects/{ids['project']}/private", "stranger").status_code == 404
    # Even a project-author mentor must have the current NDA.
    assert call(client, "GET", f"/projects/{ids['project']}/private", "mentor").status_code == 403
    with factory() as db:
        db.add(Consent(user_id=ids["mentor"], document_version_id=ids["nda"]))
        db.commit()
    private = call(client, "GET", f"/projects/{ids['project']}/private", "mentor")
    assert private.status_code == 200
    assert private.json()["private_details"] == "SECRET NEVER PUBLIC"
    with factory() as db:
        db.add(DocumentVersion(document_id=ids["nda_doc"], version="2", content="Updated NDA", content_hash="b" * 64, published_at=utcnow() + timedelta(seconds=1)))
        db.commit()
    assert call(client, "GET", f"/projects/{ids['project']}/private", "mentor").status_code == 403


def test_acceptance_is_atomic_and_messages_are_members_only(project_api):
    client, factory, ids = project_api
    created = apply(client, ids)
    assert created.status_code == 201
    application_id = created.json()["id"]
    assert apply(client, ids).status_code == 409
    assert decide(client, application_id, "mentor2").status_code == 404
    accepted = decide(client, application_id)
    assert accepted.status_code == 200
    assert accepted.json()["status"] == "accepted"
    conversation_id = accepted.json()["conversation_id"]
    participation_id = accepted.json()["participation_id"]
    with factory() as db:
        participation = db.get(Participation, participation_id)
        assert participation.mentor_id == ids["mentor"]
        assert participation.mentee_id == ids["mentee"]
        assert participation.project_id == ids["project"]
        assert db.scalar(select(func.count(ConversationMember.id)).where(ConversationMember.conversation_id == conversation_id)) == 2
        assert db.scalar(select(func.count(Notification.id))) >= 3
        assert db.scalar(select(AuditEvent).where(AuditEvent.action == "application.accepted"))
    assert call(client, "GET", f"/projects/{ids['project']}/private").status_code == 200
    assert call(client, "POST", f"/conversations/{conversation_id}/messages", json={"body": "Let's discuss the project"}).status_code == 201
    messages = call(client, "GET", f"/conversations/{conversation_id}/messages", "mentor")
    assert messages.status_code == 200 and len(messages.json()) == 1
    assert call(client, "GET", f"/conversations/{conversation_id}/messages", "stranger").status_code == 404
    assert call(client, "POST", f"/conversations/{conversation_id}/messages", "stranger", json={"body": "intrusion"}).status_code == 404
    assert call(client, "GET", "/conversations", "stranger").json() == []
    assert call(client, "GET", "/applications", "stranger").json() == []
    assert decide(client, application_id).status_code == 409
    assert apply(client, ids, "mentee2").status_code == 409


@pytest.mark.parametrize("project_chat", [False, True])
@pytest.mark.parametrize("accepted", [False, True])
def test_conversation_titles_identify_only_the_partner(project_api, project_chat, accepted):
    client, factory, ids = project_api
    application = apply(client, ids, project_id=ids["project"] if project_chat else None)
    assert application.status_code == 201
    application_id = application.json()["id"]
    if accepted:
        decision = decide(client, application_id)
        assert decision.status_code == 200
        conversation_id = decision.json()["conversation_id"]
    else:
        # Existing seeded/pre-participation conversations also need a useful title.
        with factory() as db:
            conversation = Conversation(application_id=application_id)
            db.add(conversation)
            db.flush()
            conversation_id = conversation.id
            db.add_all([ConversationMember(conversation_id=conversation_id, user_id=ids[who]) for who in ("mentor", "mentee")])
            db.commit()

    for who, partner in (("mentor", "mentee"), ("mentee", "mentor")):
        response = call(client, "GET", "/conversations", who)
        assert response.status_code == 200
        item = next(row for row in response.json() if row["id"] == conversation_id)
        assert item["other_name"] == partner
        expected_title = f"Sample project · {partner}" if project_chat else partner
        assert item["title"] == expected_title
        assert "@example.test" not in response.text
        assert "SECRET" not in response.text
        assert "private_details" not in response.text
    assert call(client, "GET", "/conversations", "stranger").json() == []
    assert call(client, "GET", "/conversations", "admin").json() == []
    assert call(client, "GET", f"/conversations/{conversation_id}/messages", "stranger").status_code == 404


@pytest.mark.parametrize("project_chat", [False, True])
def test_multiple_conversations_have_distinct_titles(project_api, project_chat):
    client, factory, ids = project_api
    with factory() as db:
        db.get(User, ids["mentor"]).capacity = 3
        db.commit()
    for who in ("mentee", "mentee2"):
        application = apply(client, ids, who, project_id=ids["project"] if project_chat else None)
        assert application.status_code == 201
        assert decide(client, application.json()["id"]).status_code == 200
    items = call(client, "GET", "/conversations", "mentor").json()
    expected_titles = {f"Sample project · {who}" if project_chat else who for who in ("mentee", "mentee2")}
    assert {item["title"] for item in items} == expected_titles
    assert {item["other_name"] for item in items} == {"mentee", "mentee2"}


def test_unnamed_conversation_partner_does_not_expose_email(project_api):
    client, factory, ids = project_api
    application = apply(client, ids, project_id=None)
    assert decide(client, application.json()["id"]).status_code == 200
    with factory() as db:
        db.get(User, ids["mentee"]).full_name = "  "
        db.commit()
    response = call(client, "GET", "/conversations", "mentor")
    assert response.status_code == 200
    assert response.json()[0]["title"] == "Менторство"
    assert response.json()[0]["other_name"] == ""
    assert "mentee@example.test" not in response.text


def test_concurrent_acceptance_never_exceeds_mentor_capacity(project_api):
    client, factory, ids = project_api
    first = apply(client, ids).json()["id"]
    second = apply(client, ids, "mentee2").json()["id"]
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(lambda identifier: decide(client, identifier), [first, second]))
    assert sorted(response.status_code for response in responses) == [200, 409]
    with factory() as db:
        assert db.scalar(select(func.count(Participation.id))) == 1
        assert db.scalar(select(func.count(Conversation.id))) == 1
        assert db.scalar(select(func.count(Application.id)).where(Application.status == "accepted")) == 1


def test_project_capacity_and_closed_intake_are_enforced(project_api):
    client, factory, ids = project_api
    with factory() as db:
        db.get(Project, ids["project"]).capacity = 1
        db.get(User, ids["mentor"]).capacity = 3
        db.commit()
    first = apply(client, ids).json()["id"]
    second = apply(client, ids, "mentee2").json()["id"]
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(lambda identifier: decide(client, identifier), [first, second]))
    assert sorted(response.status_code for response in responses) == [200, 409]
    with factory() as db:
        db.get(User, ids["mentee"]).intake_open = False
        db.commit()
    # Mentees do not manage recruitment; their false intake flag must not block requests.
    assert apply(client, ids, project_id=None, mentor_id=ids["mentor2"]).status_code == 201
    with factory() as db:
        db.get(User, ids["mentor2"]).intake_open = False
        db.commit()
    assert apply(client, ids, "mentee2", project_id=None, mentor_id=ids["mentor2"]).status_code == 409
    with factory() as db:
        db.get(User, ids["mentor2"]).intake_open = True
        db.get(User, ids["mentor2"]).capacity = 0
        db.commit()
    assert apply(client, ids, "mentee2", project_id=None, mentor_id=ids["mentor2"]).status_code == 409


def test_mentee_project_assigns_valid_requested_mentor(project_api):
    client, factory, ids = project_api
    payload = {"title": "Mentee idea", "problem": "Need help solving a problem", "description": "A clear project description", "private_details": "author secret", "direction_id": ids["direction"], "stage": "idea", "required_skills": [], "capacity": 2}
    created = call(client, "POST", "/projects", json=payload)
    assert created.status_code == 201
    project_id = created.json()["id"]
    assert created.json()["mentor_id"] is None
    assert "private_details" not in created.json()
    assert call(client, "POST", f"/admin/projects/{project_id}/review", "admin", json={"decision": "published"}).status_code == 200
    assert apply(client, ids, "mentee2", project_id=project_id).status_code == 403
    application = apply(client, ids, project_id=project_id)
    assert application.status_code == 201
    assert decide(client, application.json()["id"]).status_code == 200
    with factory() as db:
        assert db.get(Project, project_id).mentor_id == ids["mentor"]
        participation = db.scalar(select(Participation).where(Participation.project_id == project_id))
        assert participation.mentee_id == ids["mentee"] and participation.mentor_id == ids["mentor"]
    assert call(client, "PATCH", f"/projects/{project_id}", "stranger", json={"title": "Stolen project"}).status_code == 404
    assert call(client, "PATCH", f"/projects/{project_id}", json={"title": "Updated own project"}).json()["visibility_status"] == "pending"


def test_rejection_withdrawal_and_accept_withdraw_race(project_api):
    client, factory, ids = project_api
    application_id = apply(client, ids).json()["id"]
    assert decide(client, application_id, decision="rejected").status_code == 422
    assert decide(client, application_id, decision="rejected", reason="made_up_reason").status_code == 422
    rejected = decide(client, application_id, decision="rejected", reason="skills_mismatch")
    assert rejected.status_code == 200
    assert rejected.json()["rejection_reason"] == "skills_mismatch"
    application_id = apply(client, ids).json()["id"]
    with ThreadPoolExecutor(max_workers=2) as pool:
        accepted = pool.submit(decide, client, application_id)
        withdrawn = pool.submit(call, client, "POST", f"/applications/{application_id}/withdraw")
        responses = [accepted.result(), withdrawn.result()]
    assert sorted(response.status_code for response in responses) == [200, 409]
    with factory() as db:
        application = db.get(Application, application_id)
        count = db.scalar(select(func.count(Participation.id)))
        assert (application.status == "accepted" and count == 1) or (application.status == "withdrawn" and count == 0)


def published_mentee_idea(factory, ids, owner="mentee", **changes):
    """Synthetic idea without production providers or published legal content."""
    with factory() as db:
        values = {"owner_id": ids[owner], "direction_id": ids["direction"],
                  "title": "Synthetic mentee idea", "problem": "Meaningful project problem",
                  "description": "Public description of a synthetic idea",
                  "private_details": "PRIVATE IDEA MATERIAL", "capacity": 2,
                  "visibility_status": "published", "stage": "idea"}
        values.update(changes)
        project = Project(**values)
        db.add(project)
        db.commit()
        return project.id


def offer(client, project_id, who="mentor", **changes):
    payload = {"motivation": "I can help develop this mentee idea"}
    payload.update(changes)
    return call(client, "POST", f"/projects/{project_id}/mentor-offers", who, json=payload)


def assert_no_matching_side_effects(factory):
    with factory() as db:
        for model in (Participation, Conversation, ConversationMember, ProjectMember):
            assert db.scalar(select(func.count(model.id))) == 0


def test_mentor_offer_is_visible_only_to_parties_and_owner_accepts(project_api):
    client, factory, ids = project_api
    project_id = published_mentee_idea(factory, ids)
    created = offer(client, project_id)
    assert created.status_code == 201, created.text
    row = created.json()
    assert row["initiator_role"] == "mentor"
    assert row["initiator_id"] == ids["mentor"]
    assert row["decision_user_id"] == ids["mentee"]
    assert row["project_id"] == project_id
    assert row["status"] == "pending"
    assert "PRIVATE IDEA" not in created.text and "private_details" not in row
    assert_no_matching_side_effects(factory)
    for who in ("mentee", "mentor"):
        visible = call(client, "GET", "/applications", who)
        assert visible.status_code == 200
        assert [item["id"] for item in visible.json()] == [row["id"]]
    for who in ("stranger", "mentor2", "admin"):
        assert call(client, "GET", "/applications", who).json() == []
    assert offer(client, project_id).status_code == 409
    for who in ("mentor", "mentor2", "stranger", "admin"):
        assert decide(client, row["id"], who).status_code == 404
    accepted = decide(client, row["id"], "mentee")
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["status"] == "accepted"
    conversation_id = accepted.json()["conversation_id"]
    with factory() as db:
        assert db.get(Project, project_id).mentor_id == ids["mentor"]
        participation = db.get(Participation, accepted.json()["participation_id"])
        assert (participation.project_id, participation.mentee_id, participation.mentor_id) == (project_id, ids["mentee"], ids["mentor"])
        assert db.scalar(select(func.count(Participation.id))) == 1
        assert db.scalar(select(func.count(Conversation.id))) == 1
        assert set(db.scalars(select(ConversationMember.user_id).where(ConversationMember.conversation_id == conversation_id))) == {ids["mentee"], ids["mentor"]}
        assert set(db.scalars(select(ProjectMember.user_id).where(ProjectMember.project_id == project_id))) == {ids["mentee"], ids["mentor"]}
    assert decide(client, row["id"], "mentee").status_code == 409
    assert call(client, "POST", f"/applications/{row['id']}/withdraw", "mentor").status_code == 409
    assert call(client, "POST", f"/conversations/{conversation_id}/messages", "mentor", json={"body": "Let us discuss the idea"}).status_code == 201
    assert len(call(client, "GET", f"/conversations/{conversation_id}/messages", "mentee").json()) == 1
    assert call(client, "GET", f"/conversations/{conversation_id}/messages", "stranger").status_code == 404
    # Receiving or accepting an offer never replaces the required private-project NDA.
    assert call(client, "GET", f"/projects/{project_id}/private", "mentor").status_code == 403


def test_mentor_offer_rejection_and_withdrawal_use_opposite_roles(project_api):
    client, factory, ids = project_api
    project_id = published_mentee_idea(factory, ids)
    first = offer(client, project_id).json()["id"]
    assert decide(client, first, "mentee", decision="rejected").status_code == 422
    rejected = decide(client, first, "mentee", decision="rejected", reason="not_a_fit")
    assert rejected.status_code == 200, rejected.text
    assert rejected.json()["status"] == "rejected"
    assert rejected.json()["rejection_reason"] == "not_a_fit"
    second = offer(client, project_id).json()["id"]
    assert call(client, "POST", f"/applications/{second}/withdraw", "mentee").status_code == 409
    assert call(client, "POST", f"/applications/{second}/withdraw", "mentor2").status_code == 409
    withdrawn = call(client, "POST", f"/applications/{second}/withdraw", "mentor")
    assert withdrawn.status_code == 200 and withdrawn.json()["status"] == "withdrawn"
    assert decide(client, second, "mentee").status_code == 409
    assert_no_matching_side_effects(factory)


@pytest.mark.parametrize("who", ["mentee", "stranger", "admin"])
def test_only_mentors_can_offer_to_mentee_ideas(project_api, who):
    client, factory, ids = project_api
    project_id = published_mentee_idea(factory, ids)
    assert offer(client, project_id, who).status_code == 403
    assert_no_matching_side_effects(factory)


@pytest.mark.parametrize("visibility", ["draft", "pending", "hidden"])
def test_mentor_offer_requires_published_idea(project_api, visibility):
    client, factory, ids = project_api
    project_id = published_mentee_idea(factory, ids, visibility_status=visibility)
    assert offer(client, project_id).status_code == 404
    assert_no_matching_side_effects(factory)


def test_mentor_offer_rejects_missing_mentor_owned_and_assigned_projects(project_api):
    client, factory, ids = project_api
    assert offer(client, str(uuid4())).status_code == 404
    assert offer(client, ids["project"]).status_code == 409
    assert offer(client, ids["project"], "mentor2").status_code == 409
    assigned = published_mentee_idea(factory, ids, mentor_id=ids["mentor2"])
    assert offer(client, assigned).status_code == 409
    assert_no_matching_side_effects(factory)


@pytest.mark.parametrize("who", ["mentor", "mentee"])
@pytest.mark.parametrize("change", ["pending", "suspended", "incomplete", "incomplete_flag"])
def test_offer_rechecks_both_profiles_before_matching(project_api, who, change):
    client, factory, ids = project_api
    project_id = published_mentee_idea(factory, ids)
    with factory() as db:
        user = db.get(User, ids[who])
        if change == "incomplete":
            user.bio = ""
        elif change == "incomplete_flag":
            user.profile_completed = False
        else:
            user.account_status = change
        db.commit()
    response = offer(client, project_id)
    assert response.status_code == (403 if who == "mentor" else 404), response.text
    assert_no_matching_side_effects(factory)


@pytest.mark.parametrize("who", ["mentor", "mentee"])
def test_offer_requires_latest_registration_consent_from_both_parties(project_api, who):
    client, factory, ids = project_api
    project_id = published_mentee_idea(factory, ids)
    with factory() as db:
        document = Document(slug="new-rules", title="Synthetic required rules", scope="registration", required_roles=[who])
        db.add(document)
        db.flush()
        db.add(DocumentVersion(document_id=document.id, version="1", content="Synthetic terms only", content_hash="c" * 64))
        db.commit()
    response = offer(client, project_id)
    assert response.status_code == (403 if who == "mentor" else 404), response.text
    assert_no_matching_side_effects(factory)


@pytest.mark.parametrize("who", ["mentor", "mentee"])
def test_offer_rejects_direction_mismatch(project_api, who):
    client, factory, ids = project_api
    project_id = published_mentee_idea(factory, ids)
    with factory() as db:
        other = Direction(slug="psychology", name_ru="Психология", name_kk="Психология", name_en="Psychology")
        db.add(other)
        db.flush()
        db.get(User, ids[who]).direction_ids = [other.id]
        db.commit()
    assert offer(client, project_id).status_code == 409
    assert_no_matching_side_effects(factory)


@pytest.mark.parametrize("blocking_state", ["intake_closed", "zero_capacity", "mentor_full", "project_full"])
def test_offer_creation_checks_available_capacity(project_api, blocking_state):
    client, factory, ids = project_api
    project_id = published_mentee_idea(factory, ids, capacity=1)
    with factory() as db:
        mentor = db.get(User, ids["mentor"])
        if blocking_state == "intake_closed":
            mentor.intake_open = False
        elif blocking_state == "zero_capacity":
            mentor.capacity = 0
        elif blocking_state == "mentor_full":
            db.add(Participation(mentor_id=ids["mentor"], mentee_id=ids["stranger"], status="paused"))
        else:
            db.add(ProjectMember(project_id=project_id, user_id=ids["stranger"], member_role="collaborator"))
        db.commit()
    assert offer(client, project_id).status_code == 409
    with factory() as db:
        assert db.scalar(select(func.count(Application.id))) == 0
        assert db.scalar(select(func.count(Conversation.id))) == 0


@pytest.mark.parametrize("change", ["project_hidden", "project_draft", "changed_owner", "assigned_mentor", "mentor_suspended", "mentee_suspended", "mentor_incomplete", "mentee_incomplete", "mentor_role_changed", "mentee_role_changed", "mentor_full", "project_full", "new_mentor_consent", "new_mentee_consent"])
def test_offer_acceptance_revalidates_state_changed_since_creation(project_api, change):
    client, factory, ids = project_api
    project_id = published_mentee_idea(factory, ids, capacity=1)
    offer_id = offer(client, project_id).json()["id"]
    with factory() as db:
        project = db.get(Project, project_id)
        if change.startswith("project_") and change != "project_full":
            project.visibility_status = change.removeprefix("project_")
        elif change == "changed_owner":
            project.owner_id = ids["mentee2"]
        elif change == "assigned_mentor":
            project.mentor_id = ids["mentor2"]
        elif change.endswith("suspended"):
            db.get(User, ids[change.split("_")[0]]).account_status = "suspended"
        elif change.endswith("incomplete"):
            db.get(User, ids[change.split("_")[0]]).bio = ""
        elif change.endswith("role_changed"):
            who = change.split("_")[0]
            db.get(User, ids[who]).role = "mentee" if who == "mentor" else "admin"
        elif change == "mentor_full":
            db.add(Participation(mentor_id=ids["mentor"], mentee_id=ids["stranger"], status="active"))
        elif change == "project_full":
            db.add(ProjectMember(project_id=project_id, user_id=ids["stranger"], member_role="collaborator"))
        else:
            who = change.split("_")[1]
            document = Document(slug="updated-rules", title="Synthetic updated terms", scope="registration", required_roles=[who])
            db.add(document)
            db.flush()
            db.add(DocumentVersion(document_id=document.id, version="1", content="Synthetic terms only", content_hash="d" * 64))
        db.commit()
    response = decide(client, offer_id, "mentee")
    assert response.status_code in {403, 404, 409}, response.text
    with factory() as db:
        assert db.get(Application, offer_id).status == "pending"
        assert db.scalar(select(func.count(Participation.id)).where(Participation.project_id == project_id)) == 0
        assert db.scalar(select(func.count(Conversation.id))) == 0


def test_accepting_mentor_offer_closes_competing_offers(project_api):
    client, factory, ids = project_api
    project_id = published_mentee_idea(factory, ids)
    first = offer(client, project_id).json()["id"]
    second = offer(client, project_id, "mentor2").json()["id"]
    assert decide(client, first, "mentee").status_code == 200
    assert decide(client, second, "mentee").status_code == 409
    with factory() as db:
        assert db.get(Application, second).status == "rejected"
        assert db.get(Application, second).rejection_reason == "project_closed"
        assert db.scalar(select(func.count(Participation.id))) == 1
        assert db.scalar(select(func.count(Conversation.id))) == 1


def test_competing_mentor_offer_acceptance_is_atomic(project_api):
    client, factory, ids = project_api
    project_id = published_mentee_idea(factory, ids)
    offers = [offer(client, project_id, who).json()["id"] for who in ("mentor", "mentor2")]
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(lambda identifier: decide(client, identifier, "mentee"), offers))
    assert sorted(response.status_code for response in responses) == [200, 409]
    with factory() as db:
        assert db.scalar(select(func.count(Participation.id))) == 1
        assert db.scalar(select(func.count(Conversation.id))) == 1
        assert db.scalar(select(func.count(Application.id)).where(Application.status == "accepted")) == 1
        assert db.scalar(select(func.count(Application.id)).where(Application.status == "rejected")) == 1


def test_mentor_offer_accept_withdraw_race_is_atomic(project_api):
    client, factory, ids = project_api
    project_id = published_mentee_idea(factory, ids)
    offer_id = offer(client, project_id).json()["id"]
    with ThreadPoolExecutor(max_workers=2) as pool:
        accepted = pool.submit(decide, client, offer_id, "mentee")
        withdrawn = pool.submit(call, client, "POST", f"/applications/{offer_id}/withdraw", "mentor")
        responses = [accepted.result(), withdrawn.result()]
    assert sorted(response.status_code for response in responses) == [200, 409]
    with factory() as db:
        row = db.get(Application, offer_id)
        count = db.scalar(select(func.count(Participation.id)))
        assert (row.status == "accepted" and count == 1) or (row.status == "withdrawn" and count == 0)


@pytest.mark.parametrize("motivation", ["short", "a" * 5001])
def test_mentor_offer_validates_motivation(project_api, motivation):
    client, factory, ids = project_api
    project_id = published_mentee_idea(factory, ids)
    assert offer(client, project_id, motivation=motivation).status_code == 422
    assert_no_matching_side_effects(factory)


def test_regular_mentee_application_keeps_its_decision_and_withdraw_roles(project_api):
    client, factory, ids = project_api
    created = apply(client, ids)
    assert created.status_code == 201
    row = created.json()
    assert row["initiator_role"] == "mentee"
    assert row["initiator_id"] == ids["mentee"]
    assert row["decision_user_id"] == ids["mentor"]
    assert decide(client, row["id"], "mentee").status_code == 404
    assert call(client, "POST", f"/applications/{row['id']}/withdraw", "mentor").status_code == 409
    assert decide(client, row["id"], "mentor").status_code == 200


def test_mentor_offer_project_filter_applies_before_pagination_and_never_leaks(project_api):
    client, factory, ids = project_api
    first_idea = published_mentee_idea(factory, ids)
    first_offer = offer(client, first_idea).json()["id"]
    for _ in range(3):
        other_idea = published_mentee_idea(factory, ids)
        assert offer(client, other_idea).status_code == 201
    scoped = call(client, "GET", "/applications", "mentee", params={"project_id": first_idea, "limit": 1})
    assert scoped.status_code == 200
    assert [row["id"] for row in scoped.json()] == [first_offer]
    assert call(client, "GET", "/applications", "mentee", params={"project_id": first_idea, "limit": 1, "offset": 1}).json() == []
    for who in ("stranger", "mentor2", "admin"):
        assert call(client, "GET", "/applications", who, params={"project_id": first_idea}).json() == []


def test_forum_kind_filter_applies_before_pagination(project_api):
    client, factory, ids = project_api
    idea_ids = {published_mentee_idea(factory, ids) for _ in range(2)}
    assigned = published_mentee_idea(factory, ids, mentor_id=ids["mentor"])
    ideas = call(client, "GET", "/projects", params={"kind": "ideas"})
    assert ideas.status_code == 200
    assert {row["id"] for row in ideas.json()} == idea_ids
    first_page = call(client, "GET", "/projects", params={"kind": "ideas", "limit": 1}).json()
    second_page = call(client, "GET", "/projects", params={"kind": "ideas", "limit": 1, "offset": 1}).json()
    assert len(first_page) == len(second_page) == 1
    assert {first_page[0]["id"], second_page[0]["id"]} == idea_ids
    projects = call(client, "GET", "/projects", params={"kind": "projects"})
    assert projects.status_code == 200
    assert {row["id"] for row in projects.json()} == {ids["project"], assigned}
    assert call(client, "GET", "/projects", params={"kind": "invalid"}).status_code == 422


@pytest.mark.parametrize("first_initiator", ["mentor", "mentee"])
def test_pending_request_cannot_be_duplicated_by_the_opposite_initiator(project_api, first_initiator):
    client, factory, ids = project_api
    project_id = published_mentee_idea(factory, ids)
    if first_initiator == "mentor":
        assert offer(client, project_id).status_code == 201
        assert apply(client, ids, project_id=project_id).status_code == 409
    else:
        assert apply(client, ids, project_id=project_id).status_code == 201
        assert offer(client, project_id).status_code == 409
    with factory() as db:
        assert db.scalar(select(func.count(Application.id))) == 1
    assert_no_matching_side_effects(factory)


def test_accepting_regular_mentee_request_closes_other_mentor_offers(project_api):
    client, factory, ids = project_api
    project_id = published_mentee_idea(factory, ids)
    offered_id = offer(client, project_id, "mentor2").json()["id"]
    requested_id = apply(client, ids, project_id=project_id).json()["id"]
    assert decide(client, requested_id, "mentor").status_code == 200
    assert decide(client, offered_id, "mentee").status_code == 409
    with factory() as db:
        assert db.get(Application, offered_id).rejection_reason == "project_closed"
        assert db.get(Application, offered_id).status == "rejected"
        assert db.get(Project, project_id).mentor_id == ids["mentor"]
