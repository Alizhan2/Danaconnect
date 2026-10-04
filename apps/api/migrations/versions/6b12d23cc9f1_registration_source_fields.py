"""Private source registration fields and bounded Google registration handoff.

Revision ID: 6b12d23cc9f1
Revises: 52d790adb0ae

Existing profiles receive empty workplace and unconfirmed commitment. This
revision never fabricates acceptance or changes approval/intake states.
"""
from alembic import op
import sqlalchemy as sa

revision = "6b12d23cc9f1"
down_revision = "52d790adb0ae"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("users", sa.Column("organization", sa.String(300), nullable=False, server_default=""))
    op.add_column("users", sa.Column("mentor_commitment", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("users", sa.Column("mentor_commitment_accepted_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("oauth_states", sa.Column("registration_role", sa.String(10), nullable=True))
    op.add_column("oauth_states", sa.Column("return_to", sa.String(2048), nullable=False, server_default="/dashboard"))


def downgrade():
    op.drop_column("oauth_states", "return_to")
    op.drop_column("oauth_states", "registration_role")
    op.drop_column("users", "mentor_commitment_accepted_at")
    op.drop_column("users", "mentor_commitment")
    op.drop_column("users", "organization")
