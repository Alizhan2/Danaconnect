"""Disposable SQLite database checks: python -m migrations.check_invariants.

Run only with explicit development DEMO_MODE=true. No persisted database is
changed; this validates seed idempotence and the database-level race barriers.
"""
from datetime import date, timedelta, timezone

from sqlalchemy import create_engine, event, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.models import Application, Base, Booking, Consent, Conversation, Slot, User
from app.seed import demo_id, seed_demo


def main():
    engine = create_engine("sqlite://", poolclass=StaticPool)

    @event.listens_for(engine, "connect")
    def foreign_keys(connection, _):
        connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    with Session(engine) as db:
        seed_demo(db, date(2026, 10, 1))
        counts = {table.name: db.scalar(select(func.count()).select_from(table)) for table in Base.metadata.sorted_tables}
        seed_demo(db, date(2026, 10, 2))
        assert counts == {table.name: db.scalar(select(func.count()).select_from(table)) for table in Base.metadata.sorted_tables}
        # Existing profile values survive a seed rerun.
        mentor = db.get(User, demo_id("user-mentor"))
        mentor.bio = "Locally edited demo profile"
        db.commit()
        seed_demo(db, date(2026, 10, 1))
        assert db.get(User, mentor.id).bio == "Locally edited demo profile"
        slot = db.get(Slot, demo_id("slot-ai-1"))
        assert slot.starts_at.tzinfo == timezone.utc
        assert slot.ends_at - slot.starts_at == timedelta(minutes=30)
        mentee = demo_id("user-mentee")
        other = demo_id("user-mentee-candidate")

        def rejected(record):
            try:
                with db.begin_nested():
                    db.add(record)
                    db.flush()
            except IntegrityError:
                return
            raise AssertionError(f"Database accepted forbidden {type(record).__name__}")

        first = Booking(slot_id=slot.id, mentee_id=mentee, mentor_id=mentor.id, status="scheduled")
        db.add(first)
        db.flush()
        rejected(Booking(slot_id=slot.id, mentee_id=other, mentor_id=mentor.id, status="scheduled"))
        first.status = "cancelled"
        db.flush()
        db.add(Booking(slot_id=slot.id, mentee_id=other, mentor_id=mentor.id, status="scheduled"))
        db.flush()

        rejected(Application(project_id=demo_id("project-ai"), mentee_id=other, mentor_id=mentor.id, motivation="Duplicate", status="pending"))
        direct = Application(mentee_id=mentee, mentor_id=mentor.id, motivation="Direct", status="pending")
        db.add(direct)
        db.flush()
        rejected(Application(mentee_id=mentee, mentor_id=mentor.id, motivation="Duplicate direct NULL project", status="pending"))
        direct.status = "withdrawn"
        db.flush()
        db.add(Application(mentee_id=mentee, mentor_id=mentor.id, motivation="Retry after withdrawal", status="pending"))
        db.flush()

        consent = db.scalar(select(Consent).where(Consent.user_id == mentee))
        rejected(Consent(user_id=mentee, document_version_id=consent.document_version_id))
        rejected(Booking(slot_id="missing-slot", mentee_id=mentee, mentor_id=mentor.id))
        rejected(Slot(mentor_id=mentor.id, starts_at=slot.starts_at, ends_at=slot.starts_at-timedelta(minutes=1)))
        # Nullable unique references can coexist for different unlinked records.
        db.add_all([Conversation(), Conversation()])
        db.flush()
        db.rollback()
    print(f"PASS: {len(counts)} tables; idempotent seed, UTC, FK, consent uniqueness, nullable uniqueness, pending applications, cancellation frees booking slot.")


if __name__ == "__main__":
    main()
