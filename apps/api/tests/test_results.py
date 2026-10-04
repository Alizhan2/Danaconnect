"""Isolated lifecycle/privacy regressions using real transactions and domain checks."""
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta

import pytest
from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.orm import sessionmaker

from app.auth import get_current_user, require_active, require_admin
from app.database import get_db
from app.models import (AuditEvent, Base, Booking, Consent, Direction, Document, DocumentVersion,
                        Feedback, Participation, ParticipationEvent, Project,
                        ProjectMember, Result, ShowcaseConsent, Slot, User, utcnow)
from app.routers.results import router
from app.config import settings


@pytest.fixture
def results_harness(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'results.db'}", connect_args={"check_same_thread": False, "timeout": 30})

    @event.listens_for(engine, "connect")
    def foreign_keys(connection, _):
        connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    with factory() as db:
        for identifier, role in [("mentee", "mentee"), ("mentor", "mentor"), ("stranger", "mentee"), ("admin", "admin")]:
            db.add(User(id=identifier, email=f"{identifier}@test.invalid", full_name=identifier,
                        role=role, account_status="active", profile_completed=True, city="Synthetic city", birth_date=date(2000, 1, 1), bio="Synthetic result biography", expertise="Synthetic mentoring expertise", evidence_urls=["https://example.test/synthetic"], direction_ids=["direction"], organization="Synthetic workplace", phone="+7 700 000 00 00", mentor_commitment=role == "mentor", mentor_commitment_accepted_at=utcnow() if role == "mentor" else None))
        db.add(Direction(id="direction", slug="test", name_ru="Test"))
        db.commit()
        db.add(Project(id="project", owner_id="mentee", mentor_id="mentor", direction_id="direction",
                       title="Project", problem="Public problem", description="Public description", private_details="PRIVATE_CONTACT", visibility_status="published"))
        db.commit()
        db.add_all([ProjectMember(project_id="project", user_id=identifier, member_role=identifier) for identifier in ["mentee", "mentor"]])
        db.add_all([Participation(id="participation", project_id="project", mentee_id="mentee", mentor_id="mentor", status="active"),
                    Participation(id="other", mentee_id="stranger", mentor_id="mentor", status="active")])
        db.commit()

    def sessions():
        with factory() as db:
            yield db

    def actor(x_actor: str = Header(), db=Depends(get_db)):
        return db.get(User, x_actor)

    def admin(x_actor: str = Header(), db=Depends(get_db)):
        person = db.get(User, x_actor)
        if person.role != "admin":
            raise HTTPException(403)
        return person

    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_db] = sessions
    app.dependency_overrides[require_active] = actor
    app.dependency_overrides[get_current_user] = actor
    app.dependency_overrides[require_admin] = admin
    with TestClient(app) as client:
        yield client, factory
    engine.dispose()


def headers(actor="mentee"):
    return {"x-actor": actor}


def completion(**extra):
    return {"status": "completed_successfully", "exit_reason": "goal_achieved", "artifact_url": "https://example.test/artifact", "summary": "Working prototype", **extra}


def close(client, actor="mentee", **extra):
    return client.post("/participations/participation/complete", headers=headers(actor), json=completion(**extra))


def test_structured_close_validation_and_access(results_harness):
    client, factory = results_harness
    invalid = [
        {"status": "completed_early", "summary": "Exit"},
        completion(exit_reason="lack_time"), completion(artifact_url="javascript:alert(1)"),
        completion(artifact_url="   "), completion(summary="  "), completion(artifact_url="https://user:password@example.test"),
        {"status": "completed_early", "exit_reason": "other", "summary": " "},
        {"status": "completed_early", "exit_reason": "goal_achieved", "summary": "Exit"},
        completion(meeting_count=999), completion(verification_status="verified"),
    ]
    for payload in invalid:
        response = client.post("/participations/participation/complete", headers=headers(), json=payload)
        assert response.status_code == 422, response.text
    assert close(client, "stranger").status_code == 404
    response = close(client, summary="  Working prototype  ")
    assert response.status_code == 200
    first = response.json()
    assert first["summary"] == "Working prototype" and first["verification_status"] == "pending"
    second = close(client, status="completed_early", exit_reason="lack_time", artifact_url=None, summary="Changed exit")
    assert second.json()["id"] == first["id"] and second.json()["exit_reason"] == "goal_achieved"
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(ParticipationEvent)) == 1
        assert db.scalar(select(func.count()).select_from(Result)) == 1
        assert db.get(Participation, "participation").completed_at
    assert client.get("/results", headers=headers("stranger")).json() == []
    assert client.post(f"/results/{first['id']}/verify", headers=headers()).status_code == 403
    assert client.post(f"/results/{first['id']}/verify", headers=headers("mentor")).status_code == 200


def add_booking(db, identifier, *, participation="participation", mentee="mentee", future=False, status="completed"):
    start = utcnow() + timedelta(days=1 if future else -2, minutes=len(identifier))
    slot = Slot(id="slot-" + identifier, mentor_id="mentor", starts_at=start,
                ends_at=start + timedelta(minutes=30), status="booked")
    db.add(slot)
    db.flush()
    db.add(Booking(id=identifier, slot_id=slot.id, mentee_id=mentee, mentor_id="mentor",
                   participation_id=participation, status=status))


def test_pause_close_cancel_linked_future_and_count_correct_meetings(results_harness):
    client, factory = results_harness
    with factory() as db:
        add_booking(db, "correct")
        add_booking(db, "wrong-party", mentee="stranger")
        add_booking(db, "wrong-link", participation="other", mentee="stranger")
        add_booking(db, "pending", future=True, status="scheduled")
        add_booking(db, "unconfirmed", status="scheduled")
        db.commit()
    assert client.post("/participations/participation/pause", headers=headers(), json={"reason": " "}).status_code == 422
    paused = client.post("/participations/participation/pause", headers=headers(), json={"reason": "  Travel  "})
    assert paused.status_code == 200 and paused.json()["cancelled_bookings"] == 1
    with factory() as db:
        assert db.get(Booking, "pending").status == "cancelled"
        assert db.get(Slot, "slot-pending").status == "available"
        assert db.get(Booking, "unconfirmed").status == "scheduled"
        assert db.scalar(select(ParticipationEvent)).reason == "Travel"
    assert client.post("/participations/participation/resume", headers=headers()).status_code == 200
    with factory() as db:
        add_booking(db, "next-future", future=True, status="scheduled")
        db.commit()
    result = close(client).json()
    assert result["meeting_count"] == 1
    with factory() as db:
        assert db.get(Booking, "next-future").status == "cancelled"
    assert client.post("/participations/participation/resume", headers=headers()).status_code == 409
    assert client.post("/participations/participation/pause", headers=headers(), json={"reason": "Later"}).status_code == 409


def test_late_feedback_is_optional_single_and_nps_independent(results_harness):
    client, factory = results_harness
    body = {"rating": 4, "comment": "  Thank you  "}
    assert client.post("/participations/participation/feedback", headers=headers(), json=body).status_code == 409
    close(client)
    with factory() as db:
        result = db.scalar(select(Result))
        result.completed_at = utcnow() - timedelta(days=500)
        db.commit()
    assert client.get("/results", headers=headers()).json()[0]["feedback"] == []
    assert client.post("/participations/participation/feedback", headers=headers("stranger"), json=body).status_code == 404
    feedback = client.post("/participations/participation/feedback", headers=headers(), json=body)
    assert feedback.status_code == 201 and feedback.json()["nps"] is None
    assert feedback.json()["comment"] == "Thank you" and feedback.json()["target_role"] == "mentor"
    assert client.post("/participations/participation/feedback", headers=headers(), json=body).status_code == 409
    for invalid in [{"rating": 0}, {"rating": 6}, {"rating": True}, {"rating": 5, "nps": 11}]:
        assert client.post("/participations/participation/feedback", headers=headers("mentor"), json=invalid).status_code == 422
    assert client.post("/participations/participation/feedback", headers=headers("mentor"), json={"rating": 5, "nps": 10}).status_code == 201
    metrics = client.get("/admin/analytics", headers=headers("admin")).json()
    assert metrics["feedback_count"] == 2 and metrics["average_rating"] == 4.5
    assert metrics["nps_responses"] == 1 and metrics["nps"] == 100


def consent(client, actor, accepted=True):
    return client.post("/projects/project/showcase-consent", headers=headers(actor), json={"accepted": accepted})


def test_showcase_requires_verification_all_parties_and_revoke_is_immediate(results_harness):
    client, factory = results_harness
    result = close(client).json()
    assert consent(client, "stranger").status_code == 404
    assert consent(client, "mentee").status_code == 200
    assert consent(client, "mentor").status_code == 200
    assert client.get("/showcase").json() == []
    assert client.post(f"/admin/results/{result['id']}/verify", headers=headers("admin")).status_code == 200
    showcase = client.get("/showcase").json()
    assert len(showcase) == 1 and showcase[0]["result_id"] == result["id"]
    text = str(showcase)
    assert "PRIVATE_CONTACT" not in text and "@test.invalid" not in text and "author_id" not in text
    assert consent(client, "mentor", False).status_code == 200
    assert client.get("/showcase").json() == []
    consent(client, "mentor")
    with factory() as db:
        db.add(ProjectMember(project_id="project", user_id="stranger", member_role="mentee"))
        db.commit()
    assert client.get("/showcase").json() == []
    consent(client, "stranger")
    assert len(client.get("/showcase").json()) == 1
    with factory() as db:
        db.get(User, "mentor").account_status = "changes_requested"
        db.commit()
    assert client.get("/showcase").json() == []
    assert consent(client, "mentor", False).status_code == 200


def test_new_showcase_version_requires_new_document_consent(results_harness):
    client, factory = results_harness
    result = close(client).json()
    client.post(f"/admin/results/{result['id']}/verify", headers=headers("admin"))
    consent(client, "mentee")
    consent(client, "mentor")
    assert len(client.get("/showcase").json()) == 1
    with factory() as db:
        document = Document(id="showcase-doc", slug="showcase", title="Draft", required_roles=["mentee", "mentor"], scope="showcase")
        db.add(document)
        db.flush()
        db.add(DocumentVersion(id="version", document_id=document.id, version="2", content="Draft", content_hash="demo"))
        db.commit()
    assert client.get("/showcase").json() == []
    assert consent(client, "mentor").status_code == 403
    with factory() as db:
        db.add_all([Consent(user_id=person, document_version_id="version") for person in ["mentee", "mentor"]])
        db.commit()
    assert len(client.get("/showcase").json()) == 1


def test_fresh_role_checks_and_standalone_admin_verification(results_harness):
    client, factory = results_harness
    with factory() as db:
        db.get(User, "mentee").role = "mentor"
        db.commit()
    assert close(client).status_code == 404
    with factory() as db:
        db.get(User, "mentee").role = "mentee"
        db.get(Participation, "participation").mentor_id = None
        db.commit()
    result = close(client).json()
    assert result["meeting_count"] == 0
    assert client.post(f"/admin/results/{result['id']}/verify", headers=headers("admin")).status_code == 200
    assert client.post("/participations/participation/feedback", headers=headers(), json={"rating": 5}).status_code == 403


def test_concurrent_close_is_one_immutable_result(results_harness):
    client, factory = results_harness
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(lambda actor: close(client, actor), ["mentee", "mentor"]))
    assert all(response.status_code == 200 for response in responses), [response.text for response in responses]
    assert responses[0].json()["id"] == responses[1].json()["id"]
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(Result)) == 1
        assert db.scalar(select(func.count()).select_from(ParticipationEvent)) == 1


def test_export_excludes_personal_fields_and_defends_formulas(results_harness):
    client, factory = results_harness
    result = close(client).json()
    with factory() as db:
        db.get(Result, result["id"]).exit_reason = "  =HYPERLINK('evil')"
        db.commit()
    assert client.get("/admin/results/export", headers=headers()).status_code == 403
    exported = client.get("/admin/results/export", headers=headers("admin"))
    assert exported.status_code == 200
    assert "'  =HYPERLINK" in exported.text
    assert "@test.invalid" not in exported.text and "Working prototype" not in exported.text
    assert "artifact_url" not in exported.text and "PRIVATE_CONTACT" not in exported.text


def test_synthetic_label_survives_config_toggle(results_harness, monkeypatch):
    client, factory = results_harness
    monkeypatch.setattr(settings, "demo_mode", False)
    with factory() as db:
        db.add(AuditEvent(actor_id="admin", action="demo_seed", entity_type="environment", entity_id="seed", detail={"synthetic": True}))
        db.commit()
    stats = client.get("/stats").json()
    assert stats["demo_mode"] is True and stats["cohort"] == "synthetic_demo"
    result = close(client).json()
    client.post(f"/admin/results/{result['id']}/verify", headers=headers("admin"))
    consent(client, "mentee")
    consent(client, "mentor")
    assert client.get("/showcase").json()[0]["demo_mode"] is True
    exported = client.get("/admin/results/export", headers=headers("admin"))
    assert "\r\ntrue," in exported.text
