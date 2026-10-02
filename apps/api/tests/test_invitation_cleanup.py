"""Cleanup never sends mail or grants accounts; all records are synthetic."""
from datetime import timedelta

from sqlalchemy import select

from app.auth import utcnow
from app.jobs_admin_invites import cleanup_invitations
from app.models_admin_invitations import AdminInvitation, AdminInvitationChallenge
from app.models_delivery import EmailOutbox


def seed_invitation(api, suffix, *, expired=False, proof_expired=False, status="pending"):
    now = utcnow()
    with api.factory() as db:
        row = AdminInvitation(email=suffix + "@example.test", full_name="Synthetic invitee", locale="ru",
            invited_by=api.ids["admin"], token_hash="token-" + suffix, status=status,
            expires_at=now + timedelta(days=-1 if expired else 1),
            encrypted_seed="synthetic-encrypted-seed", proof_hash="proof-" + suffix,
            proof_expires_at=now + timedelta(minutes=-1 if proof_expired else 1), proof_attempts=2)
        db.add(row)
        db.flush()
        db.add(AdminInvitationChallenge(invitation_id=row.id, email=row.email, code_hash="synthetic-hash", expires_at=now + timedelta(minutes=5)))
        db.add(EmailOutbox(dedup_key="admin-invitation:" + row.id, encrypted_payload="synthetic-encrypted-mail", status="pending"))
        db.commit()
        return row.id


def test_expired_link_revokes_proof_challenges_and_unsent_mail(integrated_api):
    api = integrated_api
    identifier = seed_invitation(api, "expired", expired=True)
    assert cleanup_invitations(api.factory) == {"expired": 1, "proofs_cleared": 0, "errors": 0}
    with api.factory() as db:
        row = db.get(AdminInvitation, identifier)
        assert row.status == "expired" and row.encrypted_seed == "" and row.proof_hash is None
        assert db.scalar(select(AdminInvitationChallenge).where(AdminInvitationChallenge.invitation_id == identifier)).consumed_at
        mail = db.scalar(select(EmailOutbox).where(EmailOutbox.dedup_key == "admin-invitation:" + identifier))
        assert mail.status == "failed" and mail.encrypted_payload == "" and mail.last_error_code == "invitation_expired"
    assert cleanup_invitations(api.factory) == {"expired": 0, "proofs_cleared": 0, "errors": 0}


def test_expired_setup_erases_seed_but_keeps_valid_invitation_for_new_email_proof(integrated_api):
    api = integrated_api
    identifier = seed_invitation(api, "proof-expired", proof_expired=True)
    assert cleanup_invitations(api.factory) == {"expired": 0, "proofs_cleared": 1, "errors": 0}
    with api.factory() as db:
        row = db.get(AdminInvitation, identifier)
        assert row.status == "pending" and row.encrypted_seed == "" and row.proof_hash is None
        assert row.proof_expires_at is None and row.proof_attempts == 0
        assert db.scalar(select(EmailOutbox).where(EmailOutbox.dedup_key == "admin-invitation:" + identifier)).status == "pending"


def test_cleanup_keeps_fresh_and_terminal_invitations(integrated_api):
    api = integrated_api
    fresh = seed_invitation(api, "fresh")
    terminal = seed_invitation(api, "accepted", expired=True, proof_expired=True, status="accepted")
    assert cleanup_invitations(api.factory) == {"expired": 0, "proofs_cleared": 0, "errors": 0}
    with api.factory() as db:
        assert db.get(AdminInvitation, fresh).encrypted_seed == "synthetic-encrypted-seed"
        assert db.get(AdminInvitation, terminal).status == "accepted"


def test_cleanup_respects_limit_and_processes_backlog_next_time(integrated_api):
    api = integrated_api
    seed_invitation(api, "backlog-a", expired=True)
    seed_invitation(api, "backlog-b", expired=True)
    assert cleanup_invitations(api.factory, limit=0)["expired"] == 0
    assert cleanup_invitations(api.factory, limit=1)["expired"] == 1
    assert cleanup_invitations(api.factory, limit=1)["expired"] == 1
