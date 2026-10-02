"""initial platform schema

Revision ID: 0001
Revises: 
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0001'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Frozen initial schema; future changes require a new revision.
    op.create_table('auth_challenges',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('email', sa.String(length=320), nullable=False),
    sa.Column('code_hash', sa.String(length=128), nullable=False),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('attempts', sa.Integer(), nullable=False),
    sa.Column('consumed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint('attempts >= 0', name='ck_challenge_attempts'),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('auth_challenges', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_auth_challenges_email'), ['email'], unique=False)
        batch_op.create_index(batch_op.f('ix_auth_challenges_expires_at'), ['expires_at'], unique=False)

    op.create_table('directions',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('slug', sa.String(length=80), nullable=False),
    sa.Column('name_ru', sa.String(length=160), nullable=False),
    sa.Column('name_kk', sa.String(length=160), nullable=False),
    sa.Column('name_en', sa.String(length=160), nullable=False),
    sa.Column('description_ru', sa.Text(), nullable=False),
    sa.Column('active', sa.Boolean(), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('slug')
    )
    op.create_table('users',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('email', sa.String(length=320), nullable=False),
    sa.Column('full_name', sa.String(length=180), nullable=False),
    sa.Column('role', sa.String(length=20), nullable=False),
    sa.Column('account_status', sa.String(length=30), nullable=False),
    sa.Column('intake_open', sa.Boolean(), nullable=False),
    sa.Column('timezone', sa.String(length=80), nullable=False),
    sa.Column('city', sa.String(length=120), nullable=False),
    sa.Column('phone', sa.String(length=40), nullable=True),
    sa.Column('birth_date', sa.Date(), nullable=True),
    sa.Column('bio', sa.Text(), nullable=False),
    sa.Column('expertise', sa.Text(), nullable=False),
    sa.Column('evidence_urls', sa.JSON(), nullable=False),
    sa.Column('direction_ids', sa.JSON(), nullable=False),
    sa.Column('capacity', sa.Integer(), nullable=False),
    sa.Column('profile_completed', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint("account_status IN ('draft','pending','active','changes_requested','suspended')", name='ck_user_status'),
    sa.CheckConstraint("role IN ('unchosen','mentee','mentor','admin')", name='ck_user_role'),
    sa.CheckConstraint('capacity >= 0', name='ck_user_capacity'),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_users_account_status'), ['account_status'], unique=False)
        batch_op.create_index(batch_op.f('ix_users_email'), ['email'], unique=True)

    op.create_table('audit_events',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('actor_id', sa.String(length=36), nullable=True),
    sa.Column('action', sa.String(length=100), nullable=False),
    sa.Column('entity_type', sa.String(length=60), nullable=False),
    sa.Column('entity_id', sa.String(length=36), nullable=False),
    sa.Column('detail', sa.JSON(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['actor_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('audit_events', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_audit_events_action'), ['action'], unique=False)
        batch_op.create_index(batch_op.f('ix_audit_events_actor_id'), ['actor_id'], unique=False)

    op.create_table('documents',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('slug', sa.String(length=100), nullable=False),
    sa.Column('title', sa.String(length=250), nullable=False),
    sa.Column('required_roles', sa.JSON(), nullable=False),
    sa.Column('direction_id', sa.String(length=36), nullable=True),
    sa.Column('scope', sa.String(length=30), nullable=False),
    sa.Column('active', sa.Boolean(), nullable=False),
    sa.CheckConstraint("scope IN ('registration','intake','private_project','showcase')", name='ck_document_scope'),
    sa.ForeignKeyConstraint(['direction_id'], ['directions.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('slug')
    )
    with op.batch_alter_table('documents', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_documents_direction_id'), ['direction_id'], unique=False)

    op.create_table('notifications',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('user_id', sa.String(length=36), nullable=False),
    sa.Column('kind', sa.String(length=60), nullable=False),
    sa.Column('title', sa.String(length=250), nullable=False),
    sa.Column('body', sa.Text(), nullable=False),
    sa.Column('read_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('notifications', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_notifications_user_id'), ['user_id'], unique=False)

    op.create_table('projects',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('owner_id', sa.String(length=36), nullable=False),
    sa.Column('mentor_id', sa.String(length=36), nullable=True),
    sa.Column('direction_id', sa.String(length=36), nullable=False),
    sa.Column('title', sa.String(length=220), nullable=False),
    sa.Column('problem', sa.Text(), nullable=False),
    sa.Column('description', sa.Text(), nullable=False),
    sa.Column('private_details', sa.Text(), nullable=False),
    sa.Column('stage', sa.String(length=50), nullable=False),
    sa.Column('required_skills', sa.JSON(), nullable=False),
    sa.Column('capacity', sa.Integer(), nullable=False),
    sa.Column('visibility_status', sa.String(length=30), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint("visibility_status IN ('draft','pending','published','hidden')", name='ck_project_visibility'),
    sa.CheckConstraint('capacity >= 1', name='ck_project_capacity'),
    sa.ForeignKeyConstraint(['direction_id'], ['directions.id'], ),
    sa.ForeignKeyConstraint(['mentor_id'], ['users.id'], ),
    sa.ForeignKeyConstraint(['owner_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('projects', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_projects_direction_id'), ['direction_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_projects_mentor_id'), ['mentor_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_projects_owner_id'), ['owner_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_projects_stage'), ['stage'], unique=False)
        batch_op.create_index(batch_op.f('ix_projects_visibility_status'), ['visibility_status'], unique=False)

    op.create_table('registration_reviews',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('user_id', sa.String(length=36), nullable=False),
    sa.Column('admin_id', sa.String(length=36), nullable=False),
    sa.Column('decision', sa.String(length=30), nullable=False),
    sa.Column('reason', sa.Text(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint("decision IN ('approved','changes_requested')", name='ck_registration_decision'),
    sa.ForeignKeyConstraint(['admin_id'], ['users.id'], ),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('registration_reviews', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_registration_reviews_user_id'), ['user_id'], unique=False)

    op.create_table('reports',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('reporter_id', sa.String(length=36), nullable=False),
    sa.Column('entity_type', sa.String(length=60), nullable=False),
    sa.Column('entity_id', sa.String(length=36), nullable=False),
    sa.Column('reason', sa.Text(), nullable=False),
    sa.Column('status', sa.String(length=30), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['reporter_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('reports', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_reports_reporter_id'), ['reporter_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_reports_status'), ['status'], unique=False)

    op.create_table('session_tokens',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('user_id', sa.String(length=36), nullable=False),
    sa.Column('token_hash', sa.String(length=128), nullable=False),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('token_hash')
    )
    with op.batch_alter_table('session_tokens', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_session_tokens_expires_at'), ['expires_at'], unique=False)
        batch_op.create_index(batch_op.f('ix_session_tokens_user_id'), ['user_id'], unique=False)

    op.create_table('slots',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('mentor_id', sa.String(length=36), nullable=False),
    sa.Column('starts_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('ends_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('timezone', sa.String(length=80), nullable=False),
    sa.Column('status', sa.String(length=30), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint("status IN ('available','booked','cancelled')", name='ck_slot_status'),
    sa.CheckConstraint('ends_at > starts_at', name='ck_slot_interval'),
    sa.ForeignKeyConstraint(['mentor_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('slots', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_slots_mentor_id'), ['mentor_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_slots_starts_at'), ['starts_at'], unique=False)
        batch_op.create_index(batch_op.f('ix_slots_status'), ['status'], unique=False)
        batch_op.create_index('uq_mentor_slot_start', ['mentor_id', 'starts_at'], unique=True, sqlite_where=sa.text("status <> 'cancelled'"), postgresql_where=sa.text("status <> 'cancelled'"))

    op.create_table('applications',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('project_id', sa.String(length=36), nullable=True),
    sa.Column('mentee_id', sa.String(length=36), nullable=False),
    sa.Column('mentor_id', sa.String(length=36), nullable=False),
    sa.Column('motivation', sa.Text(), nullable=False),
    sa.Column('status', sa.String(length=30), nullable=False),
    sa.Column('rejection_reason', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint("status IN ('pending','accepted','rejected','withdrawn')", name='ck_application_status'),
    sa.CheckConstraint('mentee_id <> mentor_id', name='ck_application_parties'),
    sa.ForeignKeyConstraint(['mentee_id'], ['users.id'], ),
    sa.ForeignKeyConstraint(['mentor_id'], ['users.id'], ),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('applications', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_applications_mentee_id'), ['mentee_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_applications_mentor_id'), ['mentor_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_applications_project_id'), ['project_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_applications_status'), ['status'], unique=False)
        batch_op.create_index('uq_pending_direct_application', ['mentee_id', 'mentor_id'], unique=True, sqlite_where=sa.text("status = 'pending' AND project_id IS NULL"), postgresql_where=sa.text("status = 'pending' AND project_id IS NULL"))
        batch_op.create_index('uq_pending_project_application', ['project_id', 'mentee_id', 'mentor_id'], unique=True, sqlite_where=sa.text("status = 'pending' AND project_id IS NOT NULL"), postgresql_where=sa.text("status = 'pending' AND project_id IS NOT NULL"))

    op.create_table('document_versions',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('document_id', sa.String(length=36), nullable=False),
    sa.Column('version', sa.String(length=40), nullable=False),
    sa.Column('content', sa.Text(), nullable=False),
    sa.Column('content_hash', sa.String(length=64), nullable=False),
    sa.Column('published_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['document_id'], ['documents.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('document_id', 'version', name='uq_document_version')
    )
    with op.batch_alter_table('document_versions', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_document_versions_document_id'), ['document_id'], unique=False)

    op.create_table('participations',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('project_id', sa.String(length=36), nullable=True),
    sa.Column('mentee_id', sa.String(length=36), nullable=False),
    sa.Column('mentor_id', sa.String(length=36), nullable=True),
    sa.Column('status', sa.String(length=40), nullable=False),
    sa.Column('started_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
    sa.CheckConstraint("status IN ('active','paused','completed_successfully','completed_early')", name='ck_participation_status'),
    sa.CheckConstraint('mentor_id IS NULL OR mentee_id <> mentor_id', name='ck_participation_parties'),
    sa.ForeignKeyConstraint(['mentee_id'], ['users.id'], ),
    sa.ForeignKeyConstraint(['mentor_id'], ['users.id'], ),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('participations', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_participations_mentee_id'), ['mentee_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_participations_mentor_id'), ['mentor_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_participations_project_id'), ['project_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_participations_status'), ['status'], unique=False)
        batch_op.create_index('uq_active_direct_participation', ['mentee_id', 'mentor_id'], unique=True, sqlite_where=sa.text("status IN ('active','paused') AND project_id IS NULL"), postgresql_where=sa.text("status IN ('active','paused') AND project_id IS NULL"))
        batch_op.create_index('uq_active_project_participation', ['project_id', 'mentee_id'], unique=True, sqlite_where=sa.text("status IN ('active','paused') AND project_id IS NOT NULL"), postgresql_where=sa.text("status IN ('active','paused') AND project_id IS NOT NULL"))

    op.create_table('project_members',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('project_id', sa.String(length=36), nullable=False),
    sa.Column('user_id', sa.String(length=36), nullable=False),
    sa.Column('member_role', sa.String(length=30), nullable=False),
    sa.Column('joined_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('project_id', 'user_id', name='uq_project_member')
    )
    with op.batch_alter_table('project_members', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_project_members_project_id'), ['project_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_project_members_user_id'), ['user_id'], unique=False)

    op.create_table('showcase_consents',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('project_id', sa.String(length=36), nullable=False),
    sa.Column('user_id', sa.String(length=36), nullable=False),
    sa.Column('accepted', sa.Boolean(), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('project_id', 'user_id', name='uq_showcase_consent')
    )
    with op.batch_alter_table('showcase_consents', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_showcase_consents_project_id'), ['project_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_showcase_consents_user_id'), ['user_id'], unique=False)

    op.create_table('bookings',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('slot_id', sa.String(length=36), nullable=False),
    sa.Column('mentee_id', sa.String(length=36), nullable=False),
    sa.Column('mentor_id', sa.String(length=36), nullable=False),
    sa.Column('participation_id', sa.String(length=36), nullable=True),
    sa.Column('status', sa.String(length=30), nullable=False),
    sa.Column('meeting_url', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint("status IN ('scheduled','completed','cancelled','no_show')", name='ck_booking_status'),
    sa.CheckConstraint('mentee_id <> mentor_id', name='ck_booking_parties'),
    sa.ForeignKeyConstraint(['mentee_id'], ['users.id'], ),
    sa.ForeignKeyConstraint(['mentor_id'], ['users.id'], ),
    sa.ForeignKeyConstraint(['participation_id'], ['participations.id'], ),
    sa.ForeignKeyConstraint(['slot_id'], ['slots.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('bookings', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_bookings_mentee_id'), ['mentee_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_bookings_mentor_id'), ['mentor_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_bookings_participation_id'), ['participation_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_bookings_slot_id'), ['slot_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_bookings_status'), ['status'], unique=False)
        batch_op.create_index('uq_scheduled_booking_slot', ['slot_id'], unique=True, sqlite_where=sa.text("status = 'scheduled'"), postgresql_where=sa.text("status = 'scheduled'"))

    op.create_table('consents',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('user_id', sa.String(length=36), nullable=False),
    sa.Column('document_version_id', sa.String(length=36), nullable=False),
    sa.Column('accepted_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('method', sa.String(length=50), nullable=False),
    sa.Column('ip_address', sa.String(length=45), nullable=True),
    sa.Column('user_agent', sa.Text(), nullable=True),
    sa.ForeignKeyConstraint(['document_version_id'], ['document_versions.id'], ),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('user_id', 'document_version_id', name='uq_user_version_consent')
    )
    with op.batch_alter_table('consents', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_consents_document_version_id'), ['document_version_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_consents_user_id'), ['user_id'], unique=False)

    op.create_table('conversations',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('application_id', sa.String(length=36), nullable=True),
    sa.Column('participation_id', sa.String(length=36), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['application_id'], ['applications.id'], ),
    sa.ForeignKeyConstraint(['participation_id'], ['participations.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('application_id'),
    sa.UniqueConstraint('participation_id')
    )
    op.create_table('feedback',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('participation_id', sa.String(length=36), nullable=False),
    sa.Column('author_id', sa.String(length=36), nullable=False),
    sa.Column('target_role', sa.String(length=30), nullable=False),
    sa.Column('rating', sa.Integer(), nullable=False),
    sa.Column('nps', sa.Integer(), nullable=True),
    sa.Column('comment', sa.Text(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint('nps IS NULL OR nps BETWEEN 0 AND 10', name='ck_feedback_nps'),
    sa.CheckConstraint('rating BETWEEN 1 AND 5', name='ck_feedback_rating'),
    sa.ForeignKeyConstraint(['author_id'], ['users.id'], ),
    sa.ForeignKeyConstraint(['participation_id'], ['participations.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('participation_id', 'author_id', name='uq_participation_feedback')
    )
    with op.batch_alter_table('feedback', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_feedback_author_id'), ['author_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_feedback_participation_id'), ['participation_id'], unique=False)

    op.create_table('participation_events',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('participation_id', sa.String(length=36), nullable=False),
    sa.Column('actor_id', sa.String(length=36), nullable=True),
    sa.Column('from_status', sa.String(length=40), nullable=True),
    sa.Column('to_status', sa.String(length=40), nullable=False),
    sa.Column('reason', sa.Text(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['actor_id'], ['users.id'], ),
    sa.ForeignKeyConstraint(['participation_id'], ['participations.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('participation_events', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_participation_events_participation_id'), ['participation_id'], unique=False)

    op.create_table('results',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('participation_id', sa.String(length=36), nullable=False),
    sa.Column('status', sa.String(length=40), nullable=False),
    sa.Column('exit_reason', sa.String(length=100), nullable=False),
    sa.Column('initiator', sa.String(length=30), nullable=False),
    sa.Column('artifact_url', sa.Text(), nullable=True),
    sa.Column('summary', sa.Text(), nullable=False),
    sa.Column('meeting_count', sa.Integer(), nullable=False),
    sa.Column('verification_status', sa.String(length=30), nullable=False),
    sa.Column('completed_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint("status IN ('completed_successfully','completed_early')", name='ck_result_status'),
    sa.CheckConstraint("verification_status IN ('pending','verified')", name='ck_result_verification'),
    sa.CheckConstraint('meeting_count >= 0', name='ck_result_meeting_count'),
    sa.ForeignKeyConstraint(['participation_id'], ['participations.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('participation_id')
    )
    with op.batch_alter_table('results', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_results_verification_status'), ['verification_status'], unique=False)

    op.create_table('conversation_members',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('conversation_id', sa.String(length=36), nullable=False),
    sa.Column('user_id', sa.String(length=36), nullable=False),
    sa.ForeignKeyConstraint(['conversation_id'], ['conversations.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('conversation_id', 'user_id', name='uq_conversation_member')
    )
    with op.batch_alter_table('conversation_members', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_conversation_members_conversation_id'), ['conversation_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_conversation_members_user_id'), ['user_id'], unique=False)

    op.create_table('messages',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('conversation_id', sa.String(length=36), nullable=False),
    sa.Column('sender_id', sa.String(length=36), nullable=False),
    sa.Column('body', sa.Text(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['conversation_id'], ['conversations.id'], ),
    sa.ForeignKeyConstraint(['sender_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('messages', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_messages_conversation_id'), ['conversation_id'], unique=False)
        batch_op.create_index('ix_messages_conversation_time', ['conversation_id', 'created_at'], unique=False)
        batch_op.create_index(batch_op.f('ix_messages_sender_id'), ['sender_id'], unique=False)




def downgrade() -> None:
    # Frozen initial schema; future changes require a new revision.
    with op.batch_alter_table('messages', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_messages_sender_id'))
        batch_op.drop_index('ix_messages_conversation_time')
        batch_op.drop_index(batch_op.f('ix_messages_conversation_id'))

    op.drop_table('messages')
    with op.batch_alter_table('conversation_members', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_conversation_members_user_id'))
        batch_op.drop_index(batch_op.f('ix_conversation_members_conversation_id'))

    op.drop_table('conversation_members')
    with op.batch_alter_table('results', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_results_verification_status'))

    op.drop_table('results')
    with op.batch_alter_table('participation_events', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_participation_events_participation_id'))

    op.drop_table('participation_events')
    with op.batch_alter_table('feedback', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_feedback_participation_id'))
        batch_op.drop_index(batch_op.f('ix_feedback_author_id'))

    op.drop_table('feedback')
    op.drop_table('conversations')
    with op.batch_alter_table('consents', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_consents_user_id'))
        batch_op.drop_index(batch_op.f('ix_consents_document_version_id'))

    op.drop_table('consents')
    with op.batch_alter_table('bookings', schema=None) as batch_op:
        batch_op.drop_index('uq_scheduled_booking_slot', sqlite_where=sa.text("status = 'scheduled'"), postgresql_where=sa.text("status = 'scheduled'"))
        batch_op.drop_index(batch_op.f('ix_bookings_status'))
        batch_op.drop_index(batch_op.f('ix_bookings_slot_id'))
        batch_op.drop_index(batch_op.f('ix_bookings_participation_id'))
        batch_op.drop_index(batch_op.f('ix_bookings_mentor_id'))
        batch_op.drop_index(batch_op.f('ix_bookings_mentee_id'))

    op.drop_table('bookings')
    with op.batch_alter_table('showcase_consents', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_showcase_consents_user_id'))
        batch_op.drop_index(batch_op.f('ix_showcase_consents_project_id'))

    op.drop_table('showcase_consents')
    with op.batch_alter_table('project_members', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_project_members_user_id'))
        batch_op.drop_index(batch_op.f('ix_project_members_project_id'))

    op.drop_table('project_members')
    with op.batch_alter_table('participations', schema=None) as batch_op:
        batch_op.drop_index('uq_active_project_participation', sqlite_where=sa.text("status IN ('active','paused') AND project_id IS NOT NULL"), postgresql_where=sa.text("status IN ('active','paused') AND project_id IS NOT NULL"))
        batch_op.drop_index('uq_active_direct_participation', sqlite_where=sa.text("status IN ('active','paused') AND project_id IS NULL"), postgresql_where=sa.text("status IN ('active','paused') AND project_id IS NULL"))
        batch_op.drop_index(batch_op.f('ix_participations_status'))
        batch_op.drop_index(batch_op.f('ix_participations_project_id'))
        batch_op.drop_index(batch_op.f('ix_participations_mentor_id'))
        batch_op.drop_index(batch_op.f('ix_participations_mentee_id'))

    op.drop_table('participations')
    with op.batch_alter_table('document_versions', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_document_versions_document_id'))

    op.drop_table('document_versions')
    with op.batch_alter_table('applications', schema=None) as batch_op:
        batch_op.drop_index('uq_pending_project_application', sqlite_where=sa.text("status = 'pending' AND project_id IS NOT NULL"), postgresql_where=sa.text("status = 'pending' AND project_id IS NOT NULL"))
        batch_op.drop_index('uq_pending_direct_application', sqlite_where=sa.text("status = 'pending' AND project_id IS NULL"), postgresql_where=sa.text("status = 'pending' AND project_id IS NULL"))
        batch_op.drop_index(batch_op.f('ix_applications_status'))
        batch_op.drop_index(batch_op.f('ix_applications_project_id'))
        batch_op.drop_index(batch_op.f('ix_applications_mentor_id'))
        batch_op.drop_index(batch_op.f('ix_applications_mentee_id'))

    op.drop_table('applications')
    with op.batch_alter_table('slots', schema=None) as batch_op:
        batch_op.drop_index('uq_mentor_slot_start', sqlite_where=sa.text("status <> 'cancelled'"), postgresql_where=sa.text("status <> 'cancelled'"))
        batch_op.drop_index(batch_op.f('ix_slots_status'))
        batch_op.drop_index(batch_op.f('ix_slots_starts_at'))
        batch_op.drop_index(batch_op.f('ix_slots_mentor_id'))

    op.drop_table('slots')
    with op.batch_alter_table('session_tokens', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_session_tokens_user_id'))
        batch_op.drop_index(batch_op.f('ix_session_tokens_expires_at'))

    op.drop_table('session_tokens')
    with op.batch_alter_table('reports', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_reports_status'))
        batch_op.drop_index(batch_op.f('ix_reports_reporter_id'))

    op.drop_table('reports')
    with op.batch_alter_table('registration_reviews', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_registration_reviews_user_id'))

    op.drop_table('registration_reviews')
    with op.batch_alter_table('projects', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_projects_visibility_status'))
        batch_op.drop_index(batch_op.f('ix_projects_stage'))
        batch_op.drop_index(batch_op.f('ix_projects_owner_id'))
        batch_op.drop_index(batch_op.f('ix_projects_mentor_id'))
        batch_op.drop_index(batch_op.f('ix_projects_direction_id'))

    op.drop_table('projects')
    with op.batch_alter_table('notifications', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_notifications_user_id'))

    op.drop_table('notifications')
    with op.batch_alter_table('documents', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_documents_direction_id'))

    op.drop_table('documents')
    with op.batch_alter_table('audit_events', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_audit_events_actor_id'))
        batch_op.drop_index(batch_op.f('ix_audit_events_action'))

    op.drop_table('audit_events')
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_users_email'))
        batch_op.drop_index(batch_op.f('ix_users_account_status'))

    op.drop_table('users')
    op.drop_table('directions')
    with op.batch_alter_table('auth_challenges', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_auth_challenges_expires_at'))
        batch_op.drop_index(batch_op.f('ix_auth_challenges_email'))

    op.drop_table('auth_challenges')

