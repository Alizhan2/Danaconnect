"""Allow an operator to authorize first-time authenticator setup on the site."""
from alembic import op
import sqlalchemy as sa

revision = "b839e12c406d"
down_revision = "94c221d8ff37"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("admin_credentials", sa.Column("enrollment_expires_at", sa.DateTime(timezone=True), nullable=True))


def downgrade():
    op.drop_column("admin_credentials", "enrollment_expires_at")
