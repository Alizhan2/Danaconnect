"""Explicit initiator for mentor offers to mentee-owned ideas.

Revision ID: 94c221d8ff37
Revises: 6b12d23cc9f1

All existing applications remain mentee-initiated. No matching, membership,
approval or consent is created by this migration.
"""
from alembic import op
import sqlalchemy as sa

revision = "94c221d8ff37"
down_revision = "6b12d23cc9f1"
branch_labels = None
depends_on = None


def upgrade():
    # An inline CHECK lets SQLite add this column without copying the parent
    # table referenced by existing conversations while foreign keys are on.
    op.add_column("applications", sa.Column("initiator_role", sa.String(10),
        sa.CheckConstraint("initiator_role IN ('mentee','mentor')", name="ck_application_initiator"),
        nullable=False, server_default="mentee"))


def downgrade():
    # Never silently reinterpret a mentor offer, including accepted history,
    # as a request the mentee submitted. An operator must preserve that history.
    offers = op.get_bind().scalar(sa.text("SELECT count(*) FROM applications WHERE initiator_role = 'mentor'"))
    if offers:
        raise RuntimeError("Preserve mentor-offer history before downgrading")
    if op.get_bind().dialect.name != "sqlite":
        op.drop_constraint("ck_application_initiator", "applications", type_="check")
    op.drop_column("applications", "initiator_role")
