"""Isolated calendar domain checks; authentication is tested by identity tests."""
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone

import pytest
from fastapi import Depends, FastAPI, Header
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.orm import sessionmaker

from app.auth import require_active
from app.database import get_db
from app.models import AuditEvent, Base, Booking, Notification, Participation, Slot, User
from app.routers.bookings import router


@pytest.fixture
def bookings_harness(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'calendar.db'}",
                           connect_args={"check_same_thread": False, "timeout": 30})

    @event.listens_for(engine, "connect")
    def foreign_keys(connection, _):
        connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    with factory() as db:
        for user_id, role in [("mentor", "mentor"), ("mentor2", "mentor"), ("m1", "mentee"), ("m2", "mentee")]:
            db.add(User(id=user_id, email=f"{user_id}@test.invalid", full_name=user_id,
                        role=role, account_status="active", profile_completed=True, intake_open=role == "mentor",
                        city="Synthetic city", organization="Synthetic workplace", phone="+7 700 000 00 00",
                        birth_date=date(2000, 1, 1), bio="Synthetic calendar biography", expertise="Synthetic mentoring expertise",
                        evidence_urls=["https://example.test/synthetic"], direction_ids=["synthetic-direction"],
                        mentor_commitment=role == "mentor", mentor_commitment_accepted_at=datetime.now(timezone.utc) if role == "mentor" else None))
        db.commit()

    def sessions():
        with factory() as db:
            yield db

    def actor(x_actor: str = Header(), db=Depends(get_db)):
        return db.get(User, x_actor)

    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_db] = sessions
    app.dependency_overrides[require_active] = actor
    with TestClient(app) as client:
        yield client, factory
    engine.dispose()


def headers(actor):
    return {"x-actor": actor}


def slot(client, mentor="mentor", start=None):
    start = start or datetime.now(timezone.utc) + timedelta(days=1)
    response = client.post("/slots", headers=headers(mentor),
                           json={"starts_at": start.isoformat(), "timezone": "Asia/Oral"})
    assert response.status_code == 201, response.text
    return response.json()


def reserve(client, slot_id, mentee="m1", **extra):
    return client.post("/bookings", headers=headers(mentee), json={"slot_id": slot_id, **extra})


def test_slot_validation_and_owner_permissions(bookings_harness):
    client, _ = bookings_harness
    start = datetime.now(timezone.utc) + timedelta(days=1)
    created = slot(client, start=start)
    assert datetime.fromisoformat(created["ends_at"]) - datetime.fromisoformat(created["starts_at"]) == timedelta(minutes=30)
    for invalid in [
        {"starts_at": "2027-01-01T12:00:00", "timezone": "Asia/Oral"},
        {"starts_at": start.isoformat(), "timezone": "Invalid/Zone"},
        {"starts_at": start.isoformat(), "ends_at": (start + timedelta(minutes=90)).isoformat(), "timezone": "UTC"},
        {"starts_at": (start - timedelta(days=2)).isoformat(), "timezone": "UTC"},
    ]:
        assert client.post("/slots", headers=headers("mentor"), json=invalid).status_code == 422
    request = {"starts_at": start.isoformat(), "timezone": "Asia/Oral"}
    assert client.post("/slots", headers=headers("m1"), json=request).status_code == 403
    assert client.post("/slots", headers=headers("mentor"), json=request).status_code == 409
    assert client.delete(f"/slots/{created['id']}", headers=headers("mentor2")).status_code == 404
    assert client.delete(f"/slots/{created['id']}", headers=headers("mentor")).status_code == 200
    assert client.delete(f"/slots/{created['id']}", headers=headers("mentor")).status_code == 200


def test_concurrent_booking_has_one_winner(bookings_harness):
    client, factory = bookings_harness
    created = slot(client)
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(lambda actor: reserve(client, created["id"], actor), ["m1", "m2"]))
    assert sorted(response.status_code for response in responses) == [201, 409]
    winner = next(response.json() for response in responses if response.status_code == 201)
    duplicate = reserve(client, created["id"], winner["mentee_id"])
    assert duplicate.status_code == 201 and duplicate.json()["id"] == winner["id"]
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(Booking).where(Booking.status == "scheduled")) == 1
        assert db.get(Slot, created["id"]).status == "booked"
        assert db.scalar(select(func.count()).select_from(Notification)) == 2


def test_concurrent_overlapping_slots_and_mentee_meetings(bookings_harness):
    client, factory = bookings_harness
    start = datetime.now(timezone.utc) + timedelta(days=1)
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(lambda shift: client.post("/slots", headers=headers("mentor"),
                       json={"starts_at": (start + timedelta(minutes=shift)).isoformat(), "timezone": "UTC"}), [0, 15]))
    assert sorted(response.status_code for response in responses) == [201, 409]
    first = next(response.json() for response in responses if response.status_code == 201)
    second = slot(client, mentor="mentor2", start=datetime.fromisoformat(first["starts_at"]))
    with ThreadPoolExecutor(max_workers=2) as pool:
        bookings = list(pool.map(lambda slot_id: reserve(client, slot_id), [first["id"], second["id"]]))
    assert sorted(response.status_code for response in bookings) == [201, 409]
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(Booking).where(Booking.status == "scheduled")) == 1


def test_cancellation_restores_exact_slot_and_is_idempotent(bookings_harness):
    client, factory = bookings_harness
    created = slot(client)
    booking = reserve(client, created["id"]).json()
    path = f"/bookings/{booking['id']}/cancel"
    assert client.post(path, headers=headers("m2")).status_code == 404
    assert client.delete(f"/slots/{created['id']}", headers=headers("mentor")).status_code == 409
    assert client.post(path, headers=headers("m1")).status_code == 200
    assert client.post(path, headers=headers("m1")).status_code == 200
    with factory() as db:
        freed = db.get(Slot, created["id"])
        assert freed.status == "available"
        assert freed.starts_at == datetime.fromisoformat(created["starts_at"])
        assert db.scalar(select(func.count()).select_from(Notification)) == 4
        assert db.scalar(select(func.count()).select_from(AuditEvent)) == 3
    assert reserve(client, created["id"], "m2").status_code == 201


def test_closed_intake_active_participation_and_pause_policy(bookings_harness):
    client, factory = bookings_harness
    created = slot(client)
    with factory() as db:
        db.get(User, "mentor").intake_open = False
        db.add(Participation(id="participation", mentee_id="m1", mentor_id="mentor", status="active"))
        db.commit()
    assert reserve(client, created["id"], "m2").status_code == 409
    assert reserve(client, created["id"], "m2", participation_id="participation").status_code == 404
    booking = reserve(client, created["id"]).json()
    assert booking["participation_id"] == "participation"
    assert client.post(f"/bookings/{booking['id']}/cancel", headers=headers("m1")).status_code == 200
    with factory() as db:
        db.get(Participation, "participation").status = "paused"
        db.commit()
    assert reserve(client, created["id"]).status_code == 409
    assert reserve(client, created["id"], participation_id="participation").status_code == 409


def test_completion_by_mentor_after_start_only(bookings_harness):
    client, factory = bookings_harness
    created = slot(client)
    booking = reserve(client, created["id"]).json()
    path = f"/bookings/{booking['id']}/complete"
    assert client.post(path, headers=headers("m1")).status_code == 403
    assert client.post(path, headers=headers("mentor")).status_code == 409
    with factory() as db:
        past = datetime.now(timezone.utc) - timedelta(minutes=45)
        db.get(Slot, created["id"]).starts_at = past
        db.get(Slot, created["id"]).ends_at = past + timedelta(minutes=30)
        db.commit()
    assert client.post(path, headers=headers("mentor")).status_code == 200
    assert client.post(path, headers=headers("mentor")).status_code == 200
    assert client.post(f"/bookings/{booking['id']}/cancel", headers=headers("mentor")).status_code == 409
    with factory() as db:
        assert db.get(Booking, booking["id"]).status == "completed"
        assert db.scalar(select(func.count()).select_from(Notification)) == 3
    assert client.get("/bookings", headers=headers("m2")).json() == []


def test_mentor_account_revalidated_before_booking(bookings_harness):
    client, factory = bookings_harness
    created = slot(client)
    with factory() as db:
        db.get(User, "mentor").account_status = "suspended"
        db.commit()
    assert reserve(client, created["id"]).status_code == 403
    assert client.get("/slots", headers=headers("m1")).json() == []
