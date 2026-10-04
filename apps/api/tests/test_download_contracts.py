"""Download contracts use synthetic accounts and disposable SQLite only."""
from datetime import timedelta

from app.models import Application, Booking, Project, Slot, User, utcnow


def test_privacy_download_contract_own_json_no_secrets(integrated_api):
    api = integrated_api
    assert api.call("GET", "/me/data-export").status_code == 401
    with api.factory() as db:
        user = db.get(User, api.ids["mentee"])
        user.full_name, user.bio, user.timezone = "Әсем Тест", "Учебная биография", "Europe/London"
        db.commit()
    for who, reason in (("mentee", "OWN-PRIVACY-REQUEST"), ("stranger", "OTHER-PRIVATE-REQUEST")):
        assert api.call("POST", "/me/privacy-requests", who, json={"kind": "export", "reason": reason}).status_code == 201
    response = api.call("GET", "/me/data-export", "mentee")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")
    assert response.headers["cache-control"] == "no-store"
    payload = response.json()
    assert payload["exported_at"] and payload["account"]["id"] == api.ids["mentee"]
    assert payload["account"]["full_name"] == "Әсем Тест"
    assert payload["account"]["timezone"] == "Europe/London"
    assert payload["privacy_requests"][0]["reason"] == "OWN-PRIVACY-REQUEST"
    for forbidden in ("OTHER-PRIVATE-REQUEST", "stranger@example.test", "mentor@example.test", "totp_secret", "session_token", "debug_code"):
        assert forbidden not in response.text


def test_privacy_export_includes_both_application_sides_and_initiator_metadata(integrated_api):
    api = integrated_api
    with api.factory() as db:
        other_mentor = User(email="other-mentor@example.test", full_name="Synthetic other mentor", role="mentor")
        db.add(other_mentor)
        db.flush()
        project = Project(owner_id=api.ids["mentee"], direction_id=api.ids["direction"], title="Synthetic export idea",
                          problem="Synthetic export test", description="Synthetic export test", private_details="PRIVATE EXPORT IDEA")
        db.add(project)
        db.flush()
        outgoing = Application(project_id=project.id, mentee_id=api.ids["mentee"], mentor_id=api.ids["mentor"], initiator_role="mentor", motivation="OWN OUTGOING OFFER", status="pending")
        incoming = Application(mentee_id=api.ids["stranger"], mentor_id=api.ids["mentor"], initiator_role="mentee", motivation="OWN INCOMING REQUEST", status="pending")
        unrelated = Application(project_id=project.id, mentee_id=api.ids["mentee"], mentor_id=other_mentor.id, initiator_role="mentor", motivation="UNRELATED MENTOR OFFER", status="pending")
        db.add_all([outgoing, incoming, unrelated])
        db.commit()
        outgoing_id, incoming_id, unrelated_id = outgoing.id, incoming.id, unrelated.id
    exported = api.call("GET", "/me/data-export", "mentor")
    assert exported.status_code == 200, exported.text
    rows = {row["id"]: row for row in exported.json()["applications"]}
    assert set(rows) == {outgoing_id, incoming_id}
    assert rows[outgoing_id]["initiator_role"] == "mentor"
    assert rows[outgoing_id]["initiator_id"] == api.ids["mentor"]
    assert rows[outgoing_id]["decision_user_id"] == api.ids["mentee"]
    assert rows[incoming_id]["initiator_role"] == "mentee"
    assert rows[incoming_id]["initiator_id"] == api.ids["stranger"]
    assert rows[incoming_id]["decision_user_id"] == api.ids["mentor"]
    for row in rows.values():
        assert row["mentor_id"] == api.ids["mentor"]
        assert "mentee_id" in row
    for forbidden in (unrelated_id, "UNRELATED MENTOR OFFER", "other-mentor@example.test", "mentee@example.test", "stranger@example.test", "PRIVATE EXPORT IDEA"):
        assert forbidden not in exported.text
    mentee_rows = api.call("GET", "/me/data-export", "mentee").json()["applications"]
    assert {row["id"] for row in mentee_rows} == {outgoing_id, unrelated_id}
    stranger_rows = api.call("GET", "/me/data-export", "stranger").json()["applications"]
    assert [row["id"] for row in stranger_rows] == [incoming_id]


def test_calendar_download_contract_only_own_utf8_events(integrated_api):
    api, starts = integrated_api, utcnow() + timedelta(days=1)
    with api.factory() as db:
        mentor = db.get(User, api.ids["mentor"])
        mentor.full_name = "Әсем; Тест, " + "Ментор " * 20
        own = Slot(mentor_id=mentor.id, starts_at=starts, ends_at=starts + timedelta(hours=1), status="booked")
        other = Slot(mentor_id=mentor.id, starts_at=starts + timedelta(hours=2), ends_at=starts + timedelta(hours=3), status="booked")
        db.add_all([own, other])
        db.flush()
        own_booking = Booking(slot_id=own.id, mentor_id=mentor.id, mentee_id=api.ids["mentee"], meeting_url="https://example.test/own-meeting")
        other_booking = Booking(slot_id=other.id, mentor_id=mentor.id, mentee_id=api.ids["stranger"], meeting_url="https://example.test/other-meeting")
        db.add_all([own_booking, other_booking])
        db.commit()
        own_id, other_id = own_booking.id, other_booking.id
    assert api.call("GET", "/me/calendar.ics").status_code == 401
    response = api.call("GET", "/me/calendar.ics", "mentee", params={"starts_after": starts.isoformat(), "ends_before": (starts + timedelta(days=2)).isoformat()})
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/calendar")
    assert response.headers["content-disposition"] == 'attachment; filename="danaconnect-calendar.ics"'
    assert response.headers["cache-control"] == "no-store"
    body = response.content.decode("utf-8")
    assert body.startswith("BEGIN:VCALENDAR\r\n") and body.endswith("END:VCALENDAR\r\n")
    assert "CLASS:PRIVATE\r\n" in body and "DTSTART:" in body
    assert f"UID:{own_id}@danaconnect" in body and other_id not in body
    assert "https://example.test/own-meeting" in body and "other-meeting" not in body
    assert r"Әсем\; Тест\," in body
    assert all(len(line.encode("utf-8")) <= 75 for line in body.split("\r\n"))


def test_calendar_download_cancelled_has_no_stale_link(integrated_api):
    api, starts = integrated_api, utcnow() + timedelta(days=1)
    with api.factory() as db:
        slot = Slot(mentor_id=api.ids["mentor"], starts_at=starts, ends_at=starts + timedelta(hours=1), status="cancelled")
        db.add(slot)
        db.flush()
        booking = Booking(slot_id=slot.id, mentor_id=api.ids["mentor"], mentee_id=api.ids["mentee"], status="cancelled", meeting_url="https://example.test/stale-meeting")
        db.add(booking)
        db.commit()
        booking_id = booking.id
    default = api.call("GET", "/me/calendar.ics", "mentee")
    assert default.status_code == 200 and booking_id not in default.text
    included = api.call("GET", "/me/calendar.ics", "mentee", params={"include_cancelled": "true"})
    assert included.status_code == 200 and booking_id in included.text
    assert "STATUS:CANCELLED" in included.text and "stale-meeting" not in included.text


def test_admin_csv_download_contract_requires_admin(integrated_api):
    api = integrated_api
    assert api.call("GET", "/admin/results/export").status_code == 401
    assert api.call("GET", "/admin/results/export", "mentee").status_code == 403
    response = api.call("GET", "/admin/results/export", "admin")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    assert response.headers["content-disposition"] == 'attachment; filename="danaconnect-results.csv"'
    assert response.headers["cache-control"] == "no-store"
    assert response.content.decode("utf-8") and "@example.test" not in response.text
