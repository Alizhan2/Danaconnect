"""Private access and weekly schedule lifecycle regressions on disposable fixtures."""
from datetime import timedelta
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import select

from app.config import settings
from app.models import (Booking, Consent, Document, DocumentVersion, Participation, Project,
                        ProjectMember, Result, Slot, User, utcnow)
from app.models_calendar import GeneratedRuleSlot


@pytest.mark.parametrize("change", ["unchanged", "edit", "disable"])
def test_weekly_calendar_changes_preserve_booked_occurrence(integrated_api, change):
    api = integrated_api
    day = utcnow().astimezone(ZoneInfo("Asia/Oral")).date() + timedelta(days=1)
    payload = {"weekday": day.weekday(), "start_time": "10:00", "end_time": "11:00",
               "timezone": "Asia/Oral", "slot_minutes": 30, "starts_on": day.isoformat(),
               "horizon_weeks": 2}
    created = api.call("POST", "/availability-rules", "mentor", json=payload)
    assert created.status_code == 201, created.text
    identifier = created.json()["rule"]["id"]
    with api.factory() as db:
        slots = list(db.scalars(select(Slot).join(GeneratedRuleSlot, GeneratedRuleSlot.slot_id == Slot.id)
                               .where(GeneratedRuleSlot.rule_id == identifier).order_by(Slot.starts_at)))
        assert len(slots) == 4
        booked_id, starts_at, ends_at = slots[0].id, slots[0].starts_at, slots[0].ends_at
        original_ids = {slot.id for slot in slots}

    reserved = api.call("POST", "/bookings", "mentee", json={"slot_id": booked_id})
    assert reserved.status_code == 201, reserved.text
    booking_id = reserved.json()["id"]
    if change == "disable":
        updated = api.call("DELETE", f"/availability-rules/{identifier}", "mentor")
    else:
        values = payload if change == "unchanged" else {**payload, "start_time": "11:00", "end_time": "12:00"}
        updated = api.call("PATCH", f"/availability-rules/{identifier}", "mentor", json=values)
    assert updated.status_code == 200, updated.text
    assert updated.json()["cancelled_free"] == (0 if change == "unchanged" else 3)
    assert updated.json()["rule"]["revision"] == (2 if change == "edit" else 1)
    if change != "disable":
        assert updated.json()["generation"]["created"] == (4 if change == "edit" else 0)

    # A change to the recurring rule never moves or cancels an existing meeting.
    for who in ("mentor", "mentee"):
        booking = next(row for row in api.call("GET", "/bookings", who).json() if row["id"] == booking_id)
        assert booking["status"] == "scheduled"
        assert booking["slot_id"] == booked_id
    with api.factory() as db:
        booked = db.get(Slot, booked_id)
        assert (booked.starts_at, booked.ends_at, booked.status) == (starts_at, ends_at, "booked")
        assert db.get(Booking, booking_id).status == "scheduled"
        for slot_id in original_ids - {booked_id}:
            assert db.get(Slot, slot_id).status == ("available" if change == "unchanged" else "cancelled")

    # Once cancelled, an occurrence from a retired rule/revision must not reopen.
    cancelled = api.call("POST", f"/bookings/{booking_id}/cancel", "mentee")
    assert cancelled.status_code == 200 and cancelled.json()["status"] == "cancelled"
    repeated = api.call("POST", f"/bookings/{booking_id}/cancel", "mentee")
    assert repeated.status_code == 200
    with api.factory() as db:
        assert db.get(Slot, booked_id).status == ("available" if change == "unchanged" else "cancelled")
    second = api.call("POST", "/bookings", "stranger", json={"slot_id": booked_id})
    assert second.status_code == (201 if change == "unchanged" else 409), second.text
    if change == "disable":
        assert api.call("PATCH", f"/availability-rules/{identifier}", "mentor", json=payload).status_code == 409
        assert api.call("POST", f"/availability-rules/{identifier}/regenerate", "mentor").status_code == 409


def test_private_attachment_rechecks_nda_membership_and_account(integrated_api, monkeypatch, tmp_path):
    api = integrated_api
    monkeypatch.setattr(settings, "storage_provider", "local")
    monkeypatch.setattr(settings, "private_upload_dir", str(tmp_path / "private"))
    with api.factory() as db:
        project = Project(owner_id=api.ids["mentor"], mentor_id=api.ids["mentor"],
                          direction_id=api.ids["direction"], title="Synthetic private project",
                          problem="Synthetic problem", description="Synthetic description")
        document = Document(slug="private-sample", title="Synthetic NDA, not legal text",
                            scope="private_project", required_roles=["mentor", "mentee"])
        db.add_all([project, document])
        db.flush()
        db.add(ProjectMember(project_id=project.id, user_id=api.ids["mentee"], member_role="mentee"))
        db.commit()
        project_id, document_id = project.id, document.id
    file_payload = {"file": ("sample.txt", b"Synthetic private material", "text/plain")}
    path = f"/projects/{project_id}/attachments"
    # A configured required NDA with no published version fails closed.
    assert api.call("POST", path, "mentor", files=file_payload).status_code == 503
    with api.factory() as db:
        version = DocumentVersion(document_id=document_id, version="1", content="Synthetic test terms",
                                  content_hash="a" * 64)
        db.add(version)
        db.flush()
        db.add(Consent(user_id=api.ids["mentor"], document_version_id=version.id))
        db.commit()
        version_id = version.id
    uploaded = api.call("POST", path, "mentor", files=file_payload)
    assert uploaded.status_code == 201, uploaded.text
    attachment_id = uploaded.json()["id"]
    download = f"/attachments/{attachment_id}/download"
    assert api.call("GET", download).status_code == 401
    assert api.call("GET", download, "stranger").status_code == 404
    assert api.call("GET", download, "mentee").status_code == 403
    assert api.call("POST", f"/documents/{version_id}/consent", "mentee").status_code == 200
    assert api.call("GET", download, "mentee").content == b"Synthetic private material"
    # A teammate can read but cannot delete another teammate's file.
    assert api.call("DELETE", f"/attachments/{attachment_id}", "mentee").status_code == 404

    with api.factory() as db:
        version = DocumentVersion(document_id=document_id, version="2", content="Updated synthetic terms",
                                  content_hash="b" * 64, published_at=utcnow() + timedelta(seconds=1))
        db.add(version)
        db.commit()
        newest_id = version.id
    for who in ("mentor", "mentee"):
        assert api.call("GET", path, who).status_code == 403
        assert api.call("GET", download, who).status_code == 403
        assert api.call("POST", f"/documents/{newest_id}/consent", who).status_code == 200
        downloaded = api.call("GET", download, who)
        assert downloaded.status_code == 200 and downloaded.content == b"Synthetic private material"
        # Global API middleware enforces no-store on all responses.
        assert "no-store" in downloaded.headers["cache-control"].split(", ")

    with api.factory() as db:
        member = db.scalar(select(ProjectMember).where(ProjectMember.project_id == project_id,
                                                       ProjectMember.user_id == api.ids["mentee"]))
        db.delete(member)
        db.commit()
    assert api.call("GET", path, "mentee").status_code == 404
    assert api.call("GET", download, "mentee").status_code == 404
    assert api.call("GET", download, "mentor").status_code == 200
    with api.factory() as db:
        db.get(User, api.ids["mentor"]).account_status = "suspended"
        db.commit()
    assert api.call("GET", download, "mentor").status_code == 403
    assert api.call("GET", download, "admin").status_code == 200


def test_showcase_current_terms_and_revocation_use_real_sessions(integrated_api):
    api = integrated_api
    with api.factory() as db:
        project = Project(owner_id=api.ids["mentee"], mentor_id=api.ids["mentor"],
                          direction_id=api.ids["direction"], title="Synthetic completed project",
                          problem="Synthetic public problem", description="Synthetic public description",
                          private_details="PRIVATE-MATERIAL-NOT-FOR-SHOWCASE", visibility_status="published")
        db.add(project)
        db.flush()
        db.add_all([ProjectMember(project_id=project.id, user_id=api.ids[who], member_role=who)
                    for who in ("mentee", "mentor")])
        participation = Participation(project_id=project.id, mentee_id=api.ids["mentee"],
                                      mentor_id=api.ids["mentor"], status="completed_successfully",
                                      started_at=utcnow() - timedelta(days=2), completed_at=utcnow())
        db.add(participation)
        db.flush()
        db.add(Result(participation_id=participation.id, status="completed_successfully",
                      exit_reason="goal_achieved", initiator="mentee", artifact_url="https://example.test/prototype",
                      summary="Synthetic finished prototype", verification_status="verified", meeting_count=0))
        db.commit()
        project_id = project.id
    path = f"/projects/{project_id}/showcase-consent"
    assert api.call("POST", path, "stranger", json={"accepted": True}).status_code == 404
    for who in ("mentee", "mentor"):
        assert api.call("POST", path, who, json={"accepted": True}).status_code == 200
    visible = api.call("GET", "/showcase")
    assert [row["id"] for row in visible.json()] == [project_id]
    assert "PRIVATE-MATERIAL" not in visible.text and "@example.test" not in visible.text

    with api.factory() as db:
        document = Document(slug="showcase-sample", title="Synthetic publication conditions",
                            scope="showcase", required_roles=["mentor", "mentee"])
        db.add(document)
        db.commit()
        document_id = document.id
    # New mandatory terms close publication until a current version is accepted.
    assert api.call("GET", "/showcase").json() == []
    assert api.call("POST", path, "mentor", json={"accepted": True}).status_code == 403
    # Revocation remains available when the new terms are not yet published/accepted.
    assert api.call("POST", path, "mentor", json={"accepted": False}).status_code == 200
    with api.factory() as db:
        version = DocumentVersion(document_id=document_id, version="1", content="Synthetic test conditions",
                                  content_hash="c" * 64)
        db.add(version)
        db.commit()
        version_id = version.id
    for who in ("mentee", "mentor"):
        assert api.call("POST", f"/documents/{version_id}/consent", who).status_code == 200
    # Document consent never overrides a user's explicit project-level revocation.
    assert api.call("GET", "/showcase").json() == []
    assert api.call("POST", path, "mentor", json={"accepted": True}).status_code == 200
    assert [row["id"] for row in api.call("GET", "/showcase").json()] == [project_id]
    assert api.call("POST", path, "mentee", json={"accepted": False}).status_code == 200
    assert api.call("GET", "/showcase").json() == []
