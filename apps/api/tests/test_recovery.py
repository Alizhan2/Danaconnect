"""Recovery drills use only synthetic SQLite records and disposable file trees.

These tests prove application behaviour after recovery, not pg_dump/pg_restore or
the production object provider. Database, objects and encryption keys are kept
separate deliberately: a database-only recovery cannot restore private files.
"""
from contextlib import contextmanager
from datetime import timedelta
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3

from cryptography.fernet import Fernet
import pytest
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.orm import sessionmaker

from app.auth import generate_totp_secret, totp_code
from app.config import settings
from app.database import get_db
from app.delivery import DeliveryFailure, DeliveryUnavailable, decrypt_text, encrypt_text
from app.main import app
from app.models import Consent, Document, DocumentVersion, Project, ProjectMember, SessionToken, utcnow
from app.models_collaboration import PrivateAttachment
from app.models_delivery import AdminCredential, EmailOutbox


def snapshot_database(factory, target):
    """Use SQLite's online backup API; copying a live DB file is not sufficient."""
    source_path = factory.kw["bind"].url.database
    assert source_path and target != Path(source_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    assert not target.exists()
    with sqlite3.connect(source_path) as source, sqlite3.connect(target) as backup:
        source.backup(backup)
        assert backup.execute("PRAGMA quick_check").fetchone() == ("ok",)
        assert backup.execute("PRAGMA foreign_key_check").fetchall() == []
    digest = hashlib.sha256(target.read_bytes()).hexdigest()
    target.with_suffix(".sha256").write_text(digest, encoding="ascii")
    return target


@contextmanager
def recovered_database(api, snapshot, target):
    """Restore to a new DB path and switch only the app's fixture dependency."""
    assert hashlib.sha256(snapshot.read_bytes()).hexdigest() == snapshot.with_suffix(".sha256").read_text(encoding="ascii")
    assert not target.exists()
    with sqlite3.connect(snapshot) as source, sqlite3.connect(target) as recovered:
        source.backup(recovered)
        assert recovered.execute("PRAGMA quick_check").fetchone() == ("ok",)
        assert recovered.execute("PRAGMA foreign_key_check").fetchall() == []
    engine = create_engine(f"sqlite:///{target}", connect_args={"check_same_thread": False, "timeout": 15})

    @event.listens_for(engine, "connect")
    def foreign_keys(connection, _):
        connection.execute("PRAGMA foreign_keys=ON")

    factory = sessionmaker(bind=engine, expire_on_commit=False)

    def isolated_recovered_db():
        with factory() as db:
            yield db

    previous_factory = api.factory
    previous_override = app.dependency_overrides[get_db]
    api.factory = factory
    app.dependency_overrides[get_db] = isolated_recovered_db
    try:
        yield factory
    finally:
        app.dependency_overrides[get_db] = previous_override
        api.factory = previous_factory
        engine.dispose()


def test_database_and_file_tree_restore_are_independent_and_recheck_access(integrated_api, monkeypatch, tmp_path):
    api = integrated_api
    source_storage = tmp_path / "source-storage"
    backup_storage = tmp_path / "object-backup"
    restored_storage = tmp_path / "restored-storage"
    monkeypatch.setattr(settings, "storage_provider", "local")
    monkeypatch.setattr(settings, "private_upload_dir", str(source_storage))
    with api.factory() as db:
        project = Project(owner_id=api.ids["mentor"], mentor_id=api.ids["mentor"],
                          direction_id=api.ids["direction"], title="Synthetic recovery project",
                          problem="Synthetic recovery problem", description="Synthetic description")
        document = Document(slug="recovery-nda", title="Synthetic test NDA, not legal text",
                            scope="private_project", required_roles=["mentor", "mentee"])
        db.add_all([project, document])
        db.flush()
        version = DocumentVersion(document_id=document.id, version="1", content="Synthetic recovery terms",
                                  content_hash="a" * 64)
        db.add(version)
        db.flush()
        db.add(ProjectMember(project_id=project.id, user_id=api.ids["mentee"], member_role="mentee"))
        db.add_all([Consent(user_id=api.ids[who], document_version_id=version.id) for who in ("mentor", "mentee")])
        db.commit()
        project_id, document_id = project.id, document.id

    body = b"SYNTHETIC_RECOVERY_PRIVATE_FILE_CONTENT_NEVER_A_PRODUCTION_FILE"
    uploaded = api.call("POST", f"/projects/{project_id}/attachments", "mentor",
                        files={"file": ("synthetic-recovery.txt", body, "text/plain")})
    assert uploaded.status_code == 201, uploaded.text
    attachment_id = uploaded.json()["id"]
    path = f"/attachments/{attachment_id}/download"
    assert api.call("GET", path, "mentee").content == body
    assert api.call("GET", path, "stranger").status_code == 404
    with api.factory() as db:
        attachment = db.get(PrivateAttachment, attachment_id)
        key, digest = attachment.storage_key, attachment.sha256
    assert digest == hashlib.sha256(body).hexdigest()

    # Object bytes, DB metadata and key custody are different recovery assets.
    original_database = api.factory.kw["bind"].url.database
    snapshot = snapshot_database(api.factory, tmp_path / "database-backup" / "synthetic.db")
    assert body not in snapshot.read_bytes()
    shutil.copytree(source_storage, backup_storage)
    object_manifest = {key: {"sha256": digest, "size_bytes": len(body)}}
    (tmp_path / "object-manifest.json").write_text(json.dumps(object_manifest), encoding="utf-8")
    assert hashlib.sha256((backup_storage / key).read_bytes()).hexdigest() == digest

    # Simulate loss/change of the original assets without touching any real DB.
    (source_storage / key).unlink()
    with api.factory() as db:
        db.get(PrivateAttachment, attachment_id).status = "deleted"
        db.commit()

    with recovered_database(api, snapshot, tmp_path / "recovered.db") as factory:
        monkeypatch.setattr(settings, "private_upload_dir", str(restored_storage))
        assert factory.kw["bind"].url.database != original_database
        with factory() as db:
            assert db.get(PrivateAttachment, attachment_id).status == "active"
        # A DB-only restore fails closed rather than claiming files survived.
        missing = api.call("GET", path, "mentee")
        assert missing.status_code == 503 and body not in missing.content
        assert api.call("GET", path, "stranger").status_code == 404

        shutil.copytree(backup_storage, restored_storage)
        restored_file = restored_storage / key
        assert restored_storage != source_storage
        assert hashlib.sha256(restored_file.read_bytes()).hexdigest() == digest
        restored = api.call("GET", path, "mentee")
        assert restored.status_code == 200 and restored.content == body
        assert "no-store" in restored.headers["cache-control"]
        assert restored.headers["content-security-policy"] == "sandbox"
        assert api.call("GET", path).status_code == 401
        assert api.call("GET", path, "stranger").status_code == 404

        # Same-length corruption exercises SHA-256, truncation exercises size.
        for corrupted in (b"X" * len(body), body[:-1]):
            restored_file.write_bytes(corrupted)
            rejected = api.call("GET", path, "mentee")
            assert rejected.status_code == 503 and body not in rejected.content
        restored_file.write_bytes(body)

        with factory() as db:
            newest = DocumentVersion(document_id=document_id, version="2", content="Updated synthetic recovery NDA",
                                     content_hash="b" * 64, published_at=utcnow() + timedelta(seconds=1))
            db.add(newest)
            db.commit()
            version_id = newest.id
        assert api.call("GET", path, "mentee").status_code == 403
        assert api.call("POST", f"/documents/{version_id}/consent", "mentee").status_code == 200
        assert api.call("GET", path, "mentee").content == body
        with factory() as db:
            member = db.scalar(select(ProjectMember).where(ProjectMember.project_id == project_id,
                                                            ProjectMember.user_id == api.ids["mentee"]))
            db.delete(member)
            db.commit()
        assert api.call("GET", path, "mentee").status_code == 404


@pytest.mark.parametrize("key_state", ["correct", "missing", "wrong", "rotated"])
def test_restored_mfa_and_outbox_need_separate_encryption_keys(integrated_api, monkeypatch, tmp_path, key_state):
    api = integrated_api
    original_key = Fernet.generate_key().decode()
    replacement_key = Fernet.generate_key().decode()
    monkeypatch.setattr(settings, "outbox_encryption_key", original_key)
    monkeypatch.setattr(settings, "outbox_previous_encryption_keys", [])
    synthetic_totp = generate_totp_secret()
    synthetic_payload = json.dumps({"recipient": "recovery@example.test", "text": "SYNTHETIC_RECOVERY_OUTBOX_BODY"})
    with api.factory() as db:
        credential = AdminCredential(user_id=api.ids["admin"], encrypted_totp_secret=encrypt_text(synthetic_totp))
        outbox = EmailOutbox(dedup_key="synthetic-recovery-outbox", encrypted_payload=encrypt_text(synthetic_payload))
        db.add_all([credential, outbox])
        db.commit()
        credential_id, outbox_id = credential.id, outbox.id
    requested = api.call("POST", "/auth/request-code", json={"email": "admin@example.test"})
    assert requested.status_code == 200, requested.text
    issued = requested.json()
    verified = api.call("POST", "/auth/verify-code", json={"challenge_id": issued["challenge_id"], "code": issued["debug_code"]})
    assert verified.status_code == 200 and verified.json()["mfa_required"] is True
    challenge_id = verified.json()["mfa_challenge_id"]
    snapshot = snapshot_database(api.factory, tmp_path / "database-backup" / "synthetic.db")
    backup_bytes = snapshot.read_bytes()
    for secret in (original_key, replacement_key, synthetic_totp, synthetic_payload):
        assert secret.encode() not in backup_bytes

    with recovered_database(api, snapshot, tmp_path / "recovered.db") as factory:
        with factory() as db:
            payload_ciphertext = db.get(EmailOutbox, outbox_id).encrypted_payload
            totp_ciphertext = db.get(AdminCredential, credential_id).encrypted_totp_secret
            assert db.scalar(select(func.count(SessionToken.id))) == 0
        # Production does not fall back to deriving an absent key from AUTH_SECRET.
        monkeypatch.setattr(settings, "environment", "production")
        if key_state == "missing":
            monkeypatch.setattr(settings, "outbox_encryption_key", "")
        elif key_state in {"wrong", "rotated"}:
            monkeypatch.setattr(settings, "outbox_encryption_key", replacement_key)
            if key_state == "rotated":
                monkeypatch.setattr(settings, "outbox_previous_encryption_keys", [original_key])
        payload = {"mfa_challenge_id": challenge_id, "code": totp_code(synthetic_totp)}
        if key_state in {"missing", "wrong"}:
            with pytest.raises((DeliveryFailure, DeliveryUnavailable)):
                decrypt_text(payload_ciphertext)
            denied = api.call("POST", "/auth/mfa/verify", json=payload)
            assert denied.status_code == 503 and "set-cookie" not in denied.headers
            for secret in (original_key, replacement_key, synthetic_totp, payload_ciphertext, totp_ciphertext, payload["code"]):
                assert secret not in denied.text
            with factory() as db:
                assert db.scalar(select(func.count(SessionToken.id))) == 0
                assert db.get(EmailOutbox, outbox_id).encrypted_payload == payload_ciphertext
            monkeypatch.setattr(settings, "outbox_encryption_key", original_key)

        assert decrypt_text(payload_ciphertext) == synthetic_payload
        assert decrypt_text(totp_ciphertext) == synthetic_totp
        restored_mfa = api.call("POST", "/auth/mfa/verify", json=payload)
        assert restored_mfa.status_code == 200 and restored_mfa.json()["role"] == "admin"
        assert "secure" in restored_mfa.headers["set-cookie"].lower()
        assert "httponly" in restored_mfa.headers["set-cookie"].lower()
        assert api.call("POST", "/auth/mfa/verify", json=payload).status_code == 410
        with factory() as db:
            assert db.scalar(select(func.count(SessionToken.id))) == 1


def test_auth_secret_controls_sessions_after_database_restore(integrated_api, monkeypatch, tmp_path):
    api = integrated_api
    assert api.call("GET", "/auth/me", "mentee").status_code == 200
    original_secret = settings.auth_secret
    snapshot = snapshot_database(api.factory, tmp_path / "database-backup" / "synthetic.db")
    assert original_secret.encode() not in snapshot.read_bytes()
    with recovered_database(api, snapshot, tmp_path / "recovered.db"):
        assert api.call("GET", "/auth/me", "mentee").status_code == 200
        monkeypatch.setattr(settings, "auth_secret", "different-isolated-recovery-secret-never-production")
        denied = api.call("GET", "/auth/me", "mentee")
        assert denied.status_code == 401 and "set-cookie" not in denied.headers
        monkeypatch.setattr(settings, "auth_secret", original_secret)
        assert api.call("GET", "/auth/me", "mentee").status_code == 200
