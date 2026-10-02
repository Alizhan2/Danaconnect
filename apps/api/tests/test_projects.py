"""Focused domain regression checks on an isolated database, including races."""
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from uuid import uuid4

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.orm import sessionmaker

from app.auth import get_current_user
from app.database import get_db
from app.models import Application, AuditEvent, Base, Consent, Conversation, ConversationMember, Direction, Document, DocumentVersion, Notification, Participation, Project, User, utcnow
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
            user = User(id=str(uuid4()), email=f"{key}@example.test", full_name=key, role=role, account_status="active", profile_completed=True, intake_open=True, capacity=1, direction_ids=[direction.id])
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
