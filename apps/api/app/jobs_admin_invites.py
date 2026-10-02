"""Bounded maintenance of expired invitation links and pending MFA secrets."""
import logging

from sqlalchemy import and_, or_, select, update

from app.admin_invitation_lifecycle import close_invitation
from app.database import SessionLocal
from app.models import utcnow
from app.models_admin_invitations import AdminInvitation


def cleanup_invitations(session_factory=SessionLocal, *, limit=200, now=None):
    now = now or utcnow()
    limit = min(max(int(limit), 0), 200)
    stats = {"expired": 0, "proofs_cleared": 0, "errors": 0}
    due = and_(AdminInvitation.status == "pending", or_(
        AdminInvitation.expires_at <= now,
        and_(AdminInvitation.proof_expires_at <= now, or_(
            AdminInvitation.encrypted_seed != "", AdminInvitation.proof_hash.is_not(None)))))
    with session_factory() as db:
        ids = list(db.scalars(select(AdminInvitation.id).where(due)
                              .order_by(AdminInvitation.expires_at, AdminInvitation.id).limit(limit)))
    for identifier in ids:
        with session_factory() as db:
            try:
                if db.get_bind().dialect.name == "sqlite":
                    db.execute(update(AdminInvitation).where(AdminInvitation.id == identifier, due)
                               .values(proof_attempts=AdminInvitation.proof_attempts))
                invitation = db.scalar(select(AdminInvitation).where(AdminInvitation.id == identifier, due)
                                       .with_for_update(skip_locked=True).execution_options(populate_existing=True))
                if invitation is None:
                    db.rollback()
                    continue
                if invitation.expires_at <= now:
                    close_invitation(db, invitation, "expired")
                    counter = "expired"
                else:
                    invitation.encrypted_seed = ""
                    invitation.proof_hash = None
                    invitation.proof_expires_at = None
                    invitation.proof_attempts = 0
                    counter = "proofs_cleared"
                db.commit()
                stats[counter] += 1
            except Exception:
                db.rollback()
                stats["errors"] += 1
                logging.getLogger("danaconnect.invitations").error("Invitation cleanup failed for record %s", identifier)
    return stats
