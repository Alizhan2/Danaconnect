from datetime import timedelta

from sqlalchemy import select

from app.auth import utcnow
from app.models import AuditEvent, ConversationMember, Participation, ProjectMember, Slot


def test_real_cookie_project_application_conversation_and_booking_flow(integrated_api):
    api = integrated_api
    # A mentee never opens intake: only mentors control recruitment.
    assert api.call("GET", "/auth/me", "mentee").json()["intake_open"] is False
    created = api.call("POST", "/projects", "mentee", json={"title": "Sample integration project", "problem": "A meaningful problem to solve", "description": "A meaningful description of our project", "private_details": "PRIVATE INTEGRATION MATERIAL", "direction_id": api.ids["direction"], "capacity": 2, "stage": "idea", "required_skills": ["Python"]})
    assert created.status_code == 201, created.text
    project_id = created.json()["id"]
    assert api.call("GET", f"/projects/{project_id}").status_code == 404
    approved = api.call("POST", f"/admin/projects/{project_id}/review", "admin", json={"decision": "published", "reason": "Sample checked"})
    assert approved.status_code == 200
    public = api.call("GET", f"/projects/{project_id}")
    assert public.status_code == 200 and "PRIVATE INTEGRATION MATERIAL" not in public.text
    applied = api.call("POST", "/applications", "mentee", json={"project_id": project_id, "mentor_id": api.ids["mentor"], "motivation": "I want to build this project with mentoring"})
    assert applied.status_code == 201, applied.text
    application_id = applied.json()["id"]
    assert api.call("POST", f"/applications/{application_id}/decision", "stranger", json={"decision": "accepted"}).status_code == 404
    accepted = api.call("POST", f"/applications/{application_id}/decision", "mentor", json={"decision": "accepted"})
    assert accepted.status_code == 200, accepted.text
    participation_id, conversation_id = accepted.json()["participation_id"], accepted.json()["conversation_id"]
    assert api.call("POST", f"/applications/{application_id}/decision", "mentor", json={"decision": "accepted"}).status_code == 409
    assert api.call("GET", f"/conversations/{conversation_id}/messages", "stranger").status_code == 404
    message = api.call("POST", f"/conversations/{conversation_id}/messages", "mentee", json={"body": "Sample private conversation"})
    assert message.status_code == 201
    assert api.call("GET", f"/conversations/{conversation_id}/messages", "mentor").json()[0]["body"] == "Sample private conversation"
    starts = utcnow() + timedelta(days=1)
    slot = api.call("POST", "/slots", "mentor", json={"starts_at": starts.isoformat(), "ends_at": (starts + timedelta(hours=1)).isoformat(), "timezone": "Asia/Oral"})
    assert slot.status_code == 201, slot.text
    booking = api.call("POST", "/bookings", "mentee", json={"slot_id": slot.json()["id"], "participation_id": participation_id})
    assert booking.status_code == 201, booking.text
    assert booking.json()["participation_id"] == participation_id
    assert api.call("POST", f"/bookings/{booking.json()['id']}/complete", "mentee").status_code == 403
    assert api.call("POST", f"/bookings/{booking.json()['id']}/complete", "mentor").status_code == 409
    # Advance only the isolated fixture's slot; no production clock/database changes.
    with api.factory() as db:
        stored_slot = db.get(Slot, slot.json()["id"])
        stored_slot.starts_at = utcnow() - timedelta(hours=2)
        stored_slot.ends_at = utcnow() - timedelta(hours=1)
        db.commit()
    completed = api.call("POST", f"/bookings/{booking.json()['id']}/complete", "mentor")
    assert completed.status_code == 200 and completed.json()["status"] == "completed"
    with api.factory() as db:
        assert db.get(Participation, participation_id).status == "active"
        assert len(list(db.scalars(select(ConversationMember).where(ConversationMember.conversation_id == conversation_id)))) == 2
        assert len(list(db.scalars(select(ProjectMember).where(ProjectMember.project_id == project_id)))) == 2
        assert db.scalar(select(AuditEvent).where(AuditEvent.action == "application.accepted")) is not None

    assert api.call("POST", f"/participations/{participation_id}/complete", "stranger", json={"status": "completed_successfully", "exit_reason": "goal_achieved", "artifact_url": "https://example.test/artifact", "summary": "Sample completed project"}).status_code == 404
    invalid = api.call("POST", f"/participations/{participation_id}/complete", "mentee", json={"status": "completed_successfully", "exit_reason": "goal_achieved"})
    assert invalid.status_code == 422
    finished = api.call("POST", f"/participations/{participation_id}/complete", "mentee", json={"status": "completed_successfully", "exit_reason": "goal_achieved", "artifact_url": "https://example.test/artifact", "summary": "Sample completed project"})
    assert finished.status_code == 200, finished.text
    assert finished.json()["meeting_count"] == 1 and finished.json()["verification_status"] == "pending"
    result_id = finished.json()["id"]
    assert api.call("GET", "/results", "stranger").json() == []
    assert api.call("GET", "/showcase").json() == []
    assert api.call("POST", f"/admin/results/{result_id}/verify", "mentee").status_code == 403
    assert api.call("POST", f"/admin/results/{result_id}/verify", "admin").json()["verification_status"] == "verified"
    feedback = api.call("POST", f"/participations/{participation_id}/feedback", "mentee", json={"rating": 5, "nps": 9, "comment": "Sample helpful mentorship"})
    assert feedback.status_code == 201
    assert api.call("POST", f"/projects/{project_id}/showcase-consent", "mentee", json={"accepted": True}).status_code == 200
    assert api.call("GET", "/showcase").json() == []
    assert api.call("POST", f"/projects/{project_id}/showcase-consent", "mentor", json={"accepted": True}).status_code == 200
    showcased = api.call("GET", "/showcase")
    assert showcased.status_code == 200 and showcased.json()[0]["id"] == project_id
    assert "PRIVATE INTEGRATION MATERIAL" not in showcased.text and "PRIVATE-PHONE" not in showcased.text
    assert "@example.test" not in showcased.text
    revoked = api.call("POST", f"/projects/{project_id}/showcase-consent", "mentor", json={"accepted": False})
    assert revoked.status_code == 200 and api.call("GET", "/showcase").json() == []
    assert api.call("POST", f"/participations/{participation_id}/resume", "mentee").status_code == 409
