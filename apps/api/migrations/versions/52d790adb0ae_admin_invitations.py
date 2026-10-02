"""Email-bound administrator invitations and private MFA admission.

Revision ID: 52d790adb0ae
Revises: 0e82eab8e5ef
"""
from alembic import op
import sqlalchemy as sa

revision = "52d790adb0ae"
down_revision = "0e82eab8e5ef"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("admin_invitations",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("email", sa.String(320), nullable=False),
        sa.Column("full_name", sa.String(160), nullable=False),
        sa.Column("locale", sa.String(2), nullable=False),
        sa.Column("invited_by", sa.String(36), nullable=False),
        sa.Column("token_hash", sa.String(128), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("accepted_user_id", sa.String(36), nullable=True),
        sa.Column("encrypted_seed", sa.Text(), nullable=False),
        sa.Column("proof_hash", sa.String(128), nullable=True),
        sa.Column("proof_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("proof_attempts", sa.Integer(), nullable=False),
        sa.CheckConstraint("status IN ('pending','accepted','revoked','expired')", name="ck_admin_invitation_status"),
        sa.CheckConstraint("locale IN ('ru','kk','en')", name="ck_admin_invitation_locale"),
        sa.CheckConstraint("proof_attempts >= 0", name="ck_admin_invitation_attempts"),
        sa.ForeignKeyConstraint(["invited_by"], ["users.id"]),
        sa.ForeignKeyConstraint(["accepted_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"), sa.UniqueConstraint("token_hash"), sa.UniqueConstraint("proof_hash"))
    op.create_index("ix_admin_invitations_email", "admin_invitations", ["email"])
    op.create_index("ix_admin_invitations_invited_by", "admin_invitations", ["invited_by"])
    op.create_index("ix_admin_invitation_due", "admin_invitations", ["status", "expires_at"])
    op.create_index("uq_admin_invitation_pending_email", "admin_invitations", ["email"], unique=True,
        postgresql_where=sa.text("status = 'pending'"), sqlite_where=sa.text("status = 'pending'"))
    op.create_table("admin_invitation_challenges",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("invitation_id", sa.String(36), nullable=False),
        sa.Column("email", sa.String(320), nullable=False),
        sa.Column("code_hash", sa.String(128), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("attempts >= 0", name="ck_admin_invitation_challenge_attempts"),
        sa.ForeignKeyConstraint(["invitation_id"], ["admin_invitations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"))
    op.create_index("ix_admin_invitation_challenges_email", "admin_invitation_challenges", ["email"])
    op.create_index("ix_admin_invitation_challenges_invitation_id", "admin_invitation_challenges", ["invitation_id"])


def downgrade():
    op.drop_table("admin_invitation_challenges")
    op.drop_table("admin_invitations")
