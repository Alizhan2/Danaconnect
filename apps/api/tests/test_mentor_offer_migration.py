"""Additive migration preserves legacy application/conversation foreign keys."""
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, event, inspect
from sqlalchemy.exc import IntegrityError

from app.config import settings


@pytest.fixture
def legacy_application_database(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "database_url", "sqlite:///" + (tmp_path / "mentor-offer-migration.db").as_posix())
    root = Path(__file__).resolve().parents[1]
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "migrations"))
    command.upgrade(config, "6b12d23cc9f1")
    engine = create_engine(settings.database_url)

    @event.listens_for(engine, "connect")
    def enforce_foreign_keys(connection, _):
        connection.execute("PRAGMA foreign_keys=ON")

    with engine.begin() as connection:
        for role in ("mentor", "mentee"):
            connection.exec_driver_sql("INSERT INTO users (id,email,full_name,role,account_status,intake_open,timezone,preferred_locale,city,bio,expertise,evidence_urls,direction_ids,capacity,profile_completed,created_at) VALUES (?,?,?,?,'active',1,'Asia/Oral','ru','Synthetic city','Synthetic biography','Synthetic expertise','[]','[]',3,1,CURRENT_TIMESTAMP)",
                                       (role, f"{role}@example.test", f"Synthetic {role}", role))
        connection.exec_driver_sql("INSERT INTO applications (id,mentee_id,mentor_id,motivation,status,created_at) VALUES ('legacy-application','mentee','mentor','Synthetic legacy application','accepted',CURRENT_TIMESTAMP)")
        connection.exec_driver_sql("INSERT INTO conversations (id,application_id,created_at) VALUES ('legacy-conversation','legacy-application',CURRENT_TIMESTAMP)")
        connection.exec_driver_sql("INSERT INTO conversation_members (id,conversation_id,user_id) VALUES ('legacy-member','legacy-conversation','mentee')")
    yield config, engine
    engine.dispose()


def assert_legacy_history(engine, initiator_column=True):
    with engine.connect() as connection:
        fields = "status,initiator_role" if initiator_column else "status"
        row = connection.exec_driver_sql(f"SELECT {fields} FROM applications WHERE id='legacy-application'").one()
        assert row == (("accepted", "mentee") if initiator_column else ("accepted",))
        assert connection.exec_driver_sql("SELECT application_id FROM conversations WHERE id='legacy-conversation'").scalar_one() == "legacy-application"
        assert connection.exec_driver_sql("SELECT user_id FROM conversation_members WHERE id='legacy-member'").scalar_one() == "mentee"
        assert connection.exec_driver_sql("PRAGMA foreign_key_check").all() == []
        assert connection.exec_driver_sql("SELECT count(*) FROM participations").scalar_one() == 0


def test_mentor_offer_migration_preserves_conversation_history_and_default(legacy_application_database):
    config, engine = legacy_application_database
    command.upgrade(config, "head")
    assert_legacy_history(engine)
    command.check(config)
    with pytest.raises(IntegrityError):
        with engine.begin() as connection:
            connection.exec_driver_sql("UPDATE applications SET initiator_role='admin' WHERE id='legacy-application'")
    command.downgrade(config, "6b12d23cc9f1")
    assert "initiator_role" not in {column["name"] for column in inspect(engine).get_columns("applications")}
    assert_legacy_history(engine, initiator_column=False)
    command.upgrade(config, "head")
    assert_legacy_history(engine)


@pytest.mark.parametrize("status", ["pending", "accepted", "rejected", "withdrawn"])
def test_mentor_offer_history_blocks_lossy_downgrade(legacy_application_database, status):
    config, engine = legacy_application_database
    command.upgrade(config, "head")
    with engine.begin() as connection:
        connection.exec_driver_sql("UPDATE applications SET initiator_role='mentor',status=? WHERE id='legacy-application'", (status,))
    with pytest.raises(RuntimeError, match="Preserve mentor-offer history"):
        command.downgrade(config, "6b12d23cc9f1")
    with engine.connect() as connection:
        assert connection.exec_driver_sql("SELECT version_num FROM alembic_version").scalar_one() == "94c221d8ff37"
        assert connection.exec_driver_sql("SELECT status,initiator_role FROM applications WHERE id='legacy-application'").one() == (status, "mentor")
        assert connection.exec_driver_sql("PRAGMA foreign_key_check").all() == []
