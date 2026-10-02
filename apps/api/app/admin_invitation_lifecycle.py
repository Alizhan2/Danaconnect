"""Admission expiry/revocation shared by HTTP routes and bounded maintenance."""
from sqlalchemy import select, update

from app.auth import utcnow
from app.models_admin_invitations import AdminInvitationChallenge
from app.models_delivery import EmailOutbox


def wipe_queued_mail(db, invitation_id, code):
    challenge_ids = list(db.scalars(select(AdminInvitationChallenge.id).where(
        AdminInvitationChallenge.invitation_id == invitation_id)).all())
    dedup_keys = ["admin-invitation:" + invitation_id, *["admin-invitation-otp:" + identifier for identifier in challenge_ids]]
    db.execute(update(EmailOutbox).where(EmailOutbox.dedup_key.in_(dedup_keys),
        EmailOutbox.status.in_(["pending", "leased"])).values(status="failed", encrypted_payload="",
        lease_token=None, lease_until=None, last_error_code=code))


def close_invitation(db, invitation, status):
    # Caller holds the invitation row lock and commits the whole admission
    # transaction. A send already started at SMTP cannot be recalled; the link
    # and proof are nevertheless invalid immediately upon this commit.
    invitation.status = status
    invitation.encrypted_seed = ""
    invitation.proof_hash = None
    invitation.proof_expires_at = None
    invitation.proof_attempts = 0
    now = utcnow()
    db.execute(update(AdminInvitationChallenge).where(
        AdminInvitationChallenge.invitation_id == invitation.id,
        AdminInvitationChallenge.consumed_at.is_(None)).values(consumed_at=now))
    wipe_queued_mail(db, invitation.id, "invitation_" + status)
