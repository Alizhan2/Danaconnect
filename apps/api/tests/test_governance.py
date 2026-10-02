from datetime import timedelta

import pytest
from sqlalchemy import select

from app.auth import utcnow
from app.models import Application, AuditEvent, Booking, Participation, SessionToken, Slot, User


def test_document_publication_permission_and_versioned_consent_history(integrated_api):
    api = integrated_api
    payload = {"slug": "mentor-sample", "title": "Sample mentor terms", "required_roles": ["mentor"], "scope": "registration", "version": "1", "content": "Development sample agreement content only, not a legal instrument."}
    assert api.call("POST", "/admin/documents", "mentee", json=payload).status_code == 403
    created = api.call("POST", "/admin/documents", "admin", json=payload)
    assert created.status_code == 201
    document_id, version_id = created.json()["document_id"], created.json()["id"]
    assert len(created.json()["content_hash"]) == 64
    assert api.call("POST", "/admin/documents", "admin", json=payload).status_code == 409
    assert api.call("POST", f"/documents/{version_id}/consent", "mentee").status_code == 403
    assert api.call("GET", "/participations", "mentor").status_code == 403
    assert api.call("POST", f"/documents/{version_id}/consent", "mentor").status_code == 200
    assert api.call("GET", "/participations", "mentor").status_code == 200
    updated = api.call("POST", f"/admin/documents/{document_id}/versions", "admin", json={"version": "2", "content": "Updated development sample agreement content only."})
    assert updated.status_code == 201
    assert api.call("GET", "/participations", "mentor").status_code == 403
    assert api.call("POST", f"/documents/{version_id}/consent", "mentor").status_code == 409
    assert api.call("POST", f"/documents/{updated.json()['id']}/consent", "mentor").status_code == 200
    history = api.call("GET", "/me/consents", "mentor").json()
    assert {(row["title"], row["version"]) for row in history} >= {("Sample mentor terms", "1"), ("Sample mentor terms", "2")}
    assert all(not {"ip_address", "user_agent", "user_id"} & row.keys() for row in history)


@pytest.mark.parametrize("blocking_record", ["active", "paused", "pending_application", "scheduled_booking"])
def test_admin_role_change_blocks_ongoing_domain_records(integrated_api, blocking_record):
    api = integrated_api
    with api.factory() as db:
        if blocking_record in {"active", "paused"}:
            db.add(Participation(mentee_id=api.ids["mentee"], mentor_id=api.ids["mentor"], status=blocking_record))
        elif blocking_record == "pending_application":
            db.add(Application(mentee_id=api.ids["mentee"], mentor_id=api.ids["mentor"], motivation="Sample motivation", status="pending"))
        else:
            slot = Slot(mentor_id=api.ids["mentor"], starts_at=utcnow() + timedelta(days=1), ends_at=utcnow() + timedelta(days=1, hours=1), status="booked")
            db.add(slot)
            db.flush()
            db.add(Booking(slot_id=slot.id, mentor_id=api.ids["mentor"], mentee_id=api.ids["mentee"], status="scheduled"))
        db.commit()
    response = api.call("PATCH", f"/admin/users/{api.ids['mentee']}/role", "admin", json={"role": "mentor", "reason": "Sample role correction"})
    assert response.status_code == 409
    with api.factory() as db:
        assert db.get(User, api.ids["mentee"]).role == "mentee"
        assert not list(db.scalars(select(AuditEvent).where(AuditEvent.action == "user.role_changed")))


def test_successful_role_change_resets_approval_and_revokes_sessions(integrated_api):
    api = integrated_api
    assert api.call("GET", "/auth/me", "mentee").status_code == 200
    payload = {"role": "mentor", "reason": "Sample role correction"}
    assert api.call("PATCH", f"/admin/users/{api.ids['mentee']}/role", "stranger", json=payload).status_code == 403
    assert api.call("PATCH", f"/admin/users/{api.ids['admin']}/role", "admin", json=payload).status_code == 409
    assert api.call("PATCH", f"/admin/users/{api.ids['mentee']}/role", "admin", json={**payload, "role": "admin"}).status_code == 422
    changed = api.call("PATCH", f"/admin/users/{api.ids['mentee']}/role", "admin", json=payload)
    assert changed.status_code == 200
    assert changed.json()["role"] == "mentor" and changed.json()["account_status"] == "draft"
    assert changed.json()["profile_completed"] is False and changed.json()["intake_open"] is False
    assert api.call("GET", "/auth/me", "mentee").status_code == 401
    with api.factory() as db:
        assert not list(db.scalars(select(SessionToken).where(SessionToken.user_id == api.ids["mentee"])))
        event = db.scalar(select(AuditEvent).where(AuditEvent.action == "user.role_changed"))
        assert event.actor_id == api.ids["admin"] and event.detail["reason"] == payload["reason"]


def test_capacity_cannot_fall_below_active_and_paused_participations(integrated_api):
    api = integrated_api
    with api.factory() as db:
        db.add_all([Participation(mentee_id=api.ids["mentee"], mentor_id=api.ids["mentor"], status="active"), Participation(mentee_id=api.ids["stranger"], mentor_id=api.ids["mentor"], status="paused")])
        db.commit()
    assert api.call("PATCH", "/me/intake", "mentor", json={"intake_open": False, "capacity": 1}).status_code == 409
    assert api.call("PUT", "/me/profile", "mentor", json=api.profile("mentor", capacity=1)).status_code == 409
    closed = api.call("PATCH", "/me/intake", "mentor", json={"intake_open": False, "capacity": 2})
    assert closed.status_code == 200 and closed.json()["intake_open"] is False
    assert api.call("PATCH", "/me/intake", "mentee", json={"intake_open": True}).status_code == 403


def test_support_report_checks_visibility_and_admin_review(integrated_api):
    api = integrated_api
    payload = {"entity_type": "mentor", "entity_id": api.ids["mentor"], "reason": "Sample report describing a specific concern"}
    report = api.call("POST", "/reports", "mentee", json=payload)
    assert report.status_code == 201
    assert api.call("GET", "/admin/reports", "mentee").status_code == 403
    assert api.call("PATCH", f"/admin/reports/{report.json()['id']}", "stranger", json={"status": "resolved", "reason": "Sample investigated"}).status_code == 403
    reviewed = api.call("PATCH", f"/admin/reports/{report.json()['id']}", "admin", json={"status": "resolved", "reason": "Sample investigated"})
    assert reviewed.status_code == 200 and reviewed.json()["status"] == "resolved"
    # An arbitrary private message cannot be reported by guessing its ID.
    hidden = api.call("POST", "/reports", "stranger", json={**payload, "entity_type": "message", "entity_id": "00000000-0000-0000-0000-000000000000"})
    assert hidden.status_code == 404
    events = api.call("GET", "/admin/audit", "admin").json()
    assert any(item["action"] == "report.reviewed" and item["actor_id"] == api.ids["admin"] for item in events)
