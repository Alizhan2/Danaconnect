from datetime import timedelta

from sqlalchemy import select

from app.auth import utcnow
from app.models import AuditEvent, ConversationMember, Participation, ProjectMember, Slot


def test_real_cookie_mentor_offer_owner_decision_conversation_and_booking(integrated_api):
    api = integrated_api
    created = api.call("POST", "/projects", "mentee", json={"title": "Synthetic offered mentorship idea", "problem": "A meaningful problem to solve", "description": "An idea proposed by a mentee seeking mentor support", "private_details": "PRIVATE OFFER MATERIAL", "direction_id": api.ids["direction"], "capacity": 2, "stage": "idea", "required_skills": ["Python"]})
    assert created.status_code == 201, created.text
    project_id = created.json()["id"]
    offer_path = f"/projects/{project_id}/mentor-offers"
    assert api.call("POST", offer_path, "anonymous", json={"motivation": "Synthetic anonymous request"}).status_code == 401
    assert api.call("POST", offer_path, "mentor", json={"motivation": "I can help you develop this idea"}).status_code == 404
    assert api.call("POST", f"/admin/projects/{project_id}/review", "admin", json={"decision": "published"}).status_code == 200
    listed = api.call("GET", "/projects", "anonymous")
    assert project_id in {row["id"] for row in listed.json()}
    assert "PRIVATE OFFER MATERIAL" not in listed.text
    offered = api.call("POST", offer_path, "mentor", json={"motivation": "I can help you develop this idea"})
    assert offered.status_code == 201, offered.text
    offer_id = offered.json()["id"]
    assert offered.json()["initiator_id"] == api.ids["mentor"]
    assert offered.json()["decision_user_id"] == api.ids["mentee"]
    assert api.call("POST", f"/applications/{offer_id}/decision", "mentor", json={"decision": "accepted"}).status_code == 404
    assert api.call("GET", "/applications", "stranger").json() == []
    accepted = api.call("POST", f"/applications/{offer_id}/decision", "mentee", json={"decision": "accepted"})
    assert accepted.status_code == 200, accepted.text
    participation_id = accepted.json()["participation_id"]
    conversation_id = accepted.json()["conversation_id"]
    assert api.call("GET", f"/conversations/{conversation_id}/messages", "stranger").status_code == 404
    assert api.call("POST", f"/conversations/{conversation_id}/messages", "mentor", json={"body": "Let us plan the first mentoring session"}).status_code == 201
    assert len(api.call("GET", f"/conversations/{conversation_id}/messages", "mentee").json()) == 1
    starts = utcnow() + timedelta(days=1)
    slot = api.call("POST", "/slots", "mentor", json={"starts_at": starts.isoformat(), "ends_at": (starts + timedelta(hours=1)).isoformat(), "timezone": "Asia/Oral"})
    assert slot.status_code == 201, slot.text
    booking = api.call("POST", "/bookings", "mentee", json={"slot_id": slot.json()["id"], "participation_id": participation_id})
    assert booking.status_code == 201, booking.text
    with api.factory() as db:
        assert db.get(Participation, participation_id).project_id == project_id
        assert len(list(db.scalars(select(ConversationMember).where(ConversationMember.conversation_id == conversation_id)))) == 2
        assert len(list(db.scalars(select(ProjectMember).where(ProjectMember.project_id == project_id)))) == 2


def test_real_cookie_forum_discussion_requires_moderation(integrated_api):
    api = integrated_api
    created = api.call("POST", "/projects", "mentee", json={"title": "Synthetic forum discussion idea", "problem": "A meaningful problem to discuss", "description": "A public idea with a moderated discussion", "private_details": "PRIVATE FORUM MATERIAL", "direction_id": api.ids["direction"], "capacity": 2, "stage": "idea", "required_skills": []})
    assert created.status_code == 201, created.text
    project_id = created.json()["id"]
    assert api.call("POST", f"/admin/projects/{project_id}/review", "admin", json={"decision": "published"}).status_code == 200
    comments_path = f"/projects/{project_id}/comments"
    posted = api.call("POST", comments_path, "mentor", json={"scope": "public", "body": "Synthetic constructive feedback for the idea"})
    assert posted.status_code == 201 and posted.json()["status"] == "pending"
    comment_id = posted.json()["id"]
    assert [row["id"] for row in api.call("GET", comments_path, "mentor").json()] == [comment_id]
    assert api.call("GET", comments_path, "mentee").json() == []
    assert api.call("GET", comments_path, "stranger").json() == []
    review_path = f"/admin/comments/{comment_id}/review"
    assert api.call("POST", review_path, "mentee", json={"decision": "visible", "reason": "Synthetic content review"}).status_code == 403
    assert api.call("POST", review_path, "admin", json={"decision": "visible", "reason": "Synthetic content review"}).status_code == 200
    visible = api.call("GET", comments_path, "stranger")
    assert [row["id"] for row in visible.json()] == [comment_id]
    assert "PRIVATE FORUM MATERIAL" not in visible.text
    assert "@example.test" not in visible.text
    assert api.call("DELETE", f"/comments/{comment_id}", "stranger").status_code == 404
    assert api.call("DELETE", f"/comments/{comment_id}", "mentor").status_code == 200
    assert api.call("GET", comments_path, "stranger").json() == []


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
