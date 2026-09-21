"""Initial CCE Schema, Tables, Constraints, and Audit Triggers

Revision ID: 0001
Revises: 
Create Date: 2026-09-21 12:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '0001'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Create Enums explicitly via raw DDL with duplicate protection
    op.execute("""
        DO $$ BEGIN
            CREATE TYPE lifecycle_status AS ENUM (
                'DRAFT', 'CONFIRMED', 'ACTIVE', 'COMPLETE',
                'CANCEL_REQUESTED', 'CANCELLED', 'SUPERSEDED', 'INVALID'
            );
        EXCEPTION WHEN duplicate_object THEN null; END $$;

        DO $$ BEGIN
            CREATE TYPE timeliness_status AS ENUM (
                'NOT_DUE', 'DUE', 'OVERDUE', 'NOT_APPLICABLE'
            );
        EXCEPTION WHEN duplicate_object THEN null; END $$;

        DO $$ BEGIN
            CREATE TYPE evidence_review_status AS ENUM (
                'NO_EVIDENCE', 'ACTION_EVIDENCE_RECEIVED',
                'AWAITING_REVIEW_EVIDENCE', 'AMBIGUOUS_REVIEW_EVIDENCE',
                'VERIFIED_COMPLETE'
            );
        EXCEPTION WHEN duplicate_object THEN null; END $$;

        DO $$ BEGIN
            CREATE TYPE ownership_status AS ENUM (
                'OWNED', 'NO_OWNER'
            );
        EXCEPTION WHEN duplicate_object THEN null; END $$;

        DO $$ BEGIN
            CREATE TYPE audit_event_type AS ENUM (
                'CREATION', 'STATE_CHANGE', 'MANUAL_OVERRIDE',
                'CANCELLATION', 'SUPERSEDED', 'OWNERSHIP_ASSIGNED', 'CONFIRMATION'
            );
        EXCEPTION WHEN duplicate_object THEN null; END $$;

        DO $$ BEGIN
            CREATE TYPE ambiguous_item_status AS ENUM (
                'OPEN', 'RESOLVED', 'OVERDUE'
            );
        EXCEPTION WHEN duplicate_object THEN null; END $$;
    """)

    lifecycle_type = postgresql.ENUM('DRAFT', 'CONFIRMED', 'ACTIVE', 'COMPLETE', 'CANCEL_REQUESTED', 'CANCELLED', 'SUPERSEDED', 'INVALID', name='lifecycle_status', create_type=False)
    timeliness_type = postgresql.ENUM('NOT_DUE', 'DUE', 'OVERDUE', 'NOT_APPLICABLE', name='timeliness_status', create_type=False)
    evidence_type = postgresql.ENUM('NO_EVIDENCE', 'ACTION_EVIDENCE_RECEIVED', 'AWAITING_REVIEW_EVIDENCE', 'AMBIGUOUS_REVIEW_EVIDENCE', 'VERIFIED_COMPLETE', name='evidence_review_status', create_type=False)
    ownership_type = postgresql.ENUM('OWNED', 'NO_OWNER', name='ownership_status', create_type=False)
    audit_event_type = postgresql.ENUM('CREATION', 'STATE_CHANGE', 'MANUAL_OVERRIDE', 'CANCELLATION', 'SUPERSEDED', 'OWNERSHIP_ASSIGNED', 'CONFIRMATION', name='audit_event_type', create_type=False)
    ambiguous_item_type = postgresql.ENUM('OPEN', 'RESOLVED', 'OVERDUE', name='ambiguous_item_status', create_type=False)

    # 2. Create obligations Table
    op.create_table(
        'obligations',
        sa.Column('id', postgresql.UUID(as_uuid=True), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('patient_id', sa.Text(), nullable=False),
        sa.Column('source_evidence', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('required_action_code', sa.String(length=128), nullable=False),
        sa.Column('required_action_description', sa.Text(), nullable=False),
        sa.Column('due_window_start', sa.DateTime(timezone=True), nullable=True),
        sa.Column('due_window_end', sa.DateTime(timezone=True), nullable=False),
        sa.Column('lifecycle_status', lifecycle_type, server_default='DRAFT', nullable=False),
        sa.Column('timeliness_status', timeliness_type, server_default='NOT_DUE', nullable=False),
        sa.Column('evidence_review_status', evidence_type, server_default='NO_EVIDENCE', nullable=False),
        sa.Column('ownership_status', ownership_type, server_default='NO_OWNER', nullable=False),
        sa.Column('assigned_team', sa.Text(), nullable=True),
        sa.Column('assigned_user_id', sa.Text(), nullable=True),
        sa.Column('superseded_by_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('migration_flag', sa.Text(), nullable=True),
        sa.Column('audit_seq', sa.Integer(), server_default='1', nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('clock_timestamp()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('clock_timestamp()'), nullable=False),
        sa.ForeignKeyConstraint(['superseded_by_id'], ['obligations.id'], ondelete='RESTRICT'),
        sa.PrimaryKeyConstraint('id'),
        sa.CheckConstraint(
            "lifecycle_status != 'SUPERSEDED' OR (superseded_by_id IS NOT NULL OR migration_flag IS NOT NULL)",
            name='chk_obligation_superseded'
        ),
        sa.CheckConstraint(
            "(ownership_status != 'OWNED') OR (assigned_team IS NOT NULL OR assigned_user_id IS NOT NULL)",
            name='chk_obligation_ownership'
        ),
        sa.CheckConstraint(
            "due_window_start IS NULL OR due_window_end >= due_window_start",
            name='chk_obligation_due_window'
        )
    )

    # Indexes on obligations
    op.create_index('idx_obligations_patient_id', 'obligations', ['patient_id'])
    op.create_index(
        'idx_obligations_dimensions',
        'obligations',
        ['lifecycle_status', 'timeliness_status', 'evidence_review_status', 'ownership_status']
    )
    op.create_index(
        'idx_obligations_active_risk',
        'obligations',
        ['timeliness_status', 'ownership_status'],
        postgresql_where=sa.text("lifecycle_status = 'ACTIVE'")
    )
    op.create_index('idx_obligations_superseded_by', 'obligations', ['superseded_by_id'])

    # 3. Create obligation_audit_log Table
    op.create_table(
        'obligation_audit_log',
        sa.Column('id', postgresql.UUID(as_uuid=True), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('obligation_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('audit_seq', sa.Integer(), nullable=False),
        sa.Column('event_type', audit_event_type, nullable=False),
        sa.Column('actor_id', sa.Text(), nullable=False),
        sa.Column('previous_state', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('new_state', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('reason_code', sa.String(length=128), nullable=False),
        sa.Column('rationale_text', sa.Text(), nullable=True),
        sa.Column('evidence_reference', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('clock_timestamp()'), nullable=False),
        sa.ForeignKeyConstraint(['obligation_id'], ['obligations.id'], ondelete='RESTRICT'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('idx_audit_log_obligation_seq', 'obligation_audit_log', ['obligation_id', 'audit_seq'])
    op.create_index('idx_audit_log_obligation_created', 'obligation_audit_log', ['obligation_id', 'created_at'])

    # 4. Create ambiguous_review_items Table
    op.create_table(
        'ambiguous_review_items',
        sa.Column('id', postgresql.UUID(as_uuid=True), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('obligation_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('proposed_evidence_snippet', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('assigned_reviewer_id', sa.Text(), nullable=True),
        sa.Column('due_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('status', ambiguous_item_type, server_default='OPEN', nullable=False),
        sa.Column('resolution_rationale', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('clock_timestamp()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('clock_timestamp()'), nullable=False),
        sa.ForeignKeyConstraint(['obligation_id'], ['obligations.id'], ondelete='RESTRICT'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('idx_ambiguous_items_obligation_id', 'ambiguous_review_items', ['obligation_id'])
    op.create_index('idx_ambiguous_items_status', 'ambiguous_review_items', ['status'])

    # 5. Create Triggers
    op.execute("""
    CREATE OR REPLACE FUNCTION prevent_obligation_deletion()
    RETURNS TRIGGER AS $$
    BEGIN
        RAISE EXCEPTION 'Clinical safety violation: Direct deletion of obligations is strictly prohibited to preserve clinical auditability. Use lifecycle cancellation or supersession instead.'
        USING ERRCODE = 'restrict_violation';
    END;
    $$ LANGUAGE plpgsql;

    DROP TRIGGER IF EXISTS trg_prevent_obligation_delete ON obligations;
    CREATE TRIGGER trg_prevent_obligation_delete
        BEFORE DELETE ON obligations
        FOR EACH ROW
        EXECUTE FUNCTION prevent_obligation_deletion();

    CREATE OR REPLACE FUNCTION prevent_audit_log_mutation()
    RETURNS TRIGGER AS $$
    BEGIN
        RAISE EXCEPTION 'Audit ledger violation: obligation_audit_log is append-only and immutable. Modifications and deletions are strictly prohibited.'
        USING ERRCODE = 'restrict_violation';
    END;
    $$ LANGUAGE plpgsql;

    DROP TRIGGER IF EXISTS trg_prevent_audit_log_mutation ON obligation_audit_log;
    CREATE TRIGGER trg_prevent_audit_log_mutation
        BEFORE UPDATE OR DELETE ON obligation_audit_log
        FOR EACH ROW
        EXECUTE FUNCTION prevent_audit_log_mutation();

    CREATE OR REPLACE FUNCTION bump_obligation_audit_seq()
    RETURNS TRIGGER AS $$
    BEGIN
        NEW.audit_seq = OLD.audit_seq + 1;
        NEW.updated_at = clock_timestamp();
        RETURN NEW;
    END;
    $$ LANGUAGE plpgsql;

    DROP TRIGGER IF EXISTS trg_obligations_increment_seq ON obligations;
    CREATE TRIGGER trg_obligations_increment_seq
        BEFORE UPDATE ON obligations
        FOR EACH ROW
        EXECUTE FUNCTION bump_obligation_audit_seq();

    CREATE OR REPLACE FUNCTION check_obligation_audit_exists()
    RETURNS TRIGGER AS $$
    BEGIN
        IF NOT EXISTS (
            SELECT 1 FROM obligation_audit_log
            WHERE obligation_id = NEW.id
              AND audit_seq = NEW.audit_seq
        ) THEN
            RAISE EXCEPTION 'Audit violation: Obligation % (audit_seq %) does not have a corresponding entry in obligation_audit_log in this transaction.',
                NEW.id, NEW.audit_seq
            USING ERRCODE = 'check_violation';
        END IF;
        RETURN NEW;
    END;
    $$ LANGUAGE plpgsql;

    DROP TRIGGER IF EXISTS trg_enforce_audit_on_mutation ON obligations;
    CREATE CONSTRAINT TRIGGER trg_enforce_audit_on_mutation
        AFTER INSERT OR UPDATE ON obligations
        DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW
        EXECUTE FUNCTION check_obligation_audit_exists();
    """)


def downgrade() -> None:
    # Drop Triggers and Functions
    op.execute("""
    DROP TRIGGER IF EXISTS trg_enforce_audit_on_mutation ON obligations;
    DROP FUNCTION IF EXISTS check_obligation_audit_exists();

    DROP TRIGGER IF EXISTS trg_obligations_increment_seq ON obligations;
    DROP FUNCTION IF EXISTS bump_obligation_audit_seq();

    DROP TRIGGER IF EXISTS trg_prevent_audit_log_mutation ON obligation_audit_log;
    DROP FUNCTION IF EXISTS prevent_audit_log_mutation();

    DROP TRIGGER IF EXISTS trg_prevent_obligation_delete ON obligations;
    DROP FUNCTION IF EXISTS prevent_obligation_deletion();
    """)

    # Drop Tables
    op.drop_table('ambiguous_review_items')
    op.drop_table('obligation_audit_log')
    op.drop_table('obligations')

    # Drop Enums
    op.execute("""
        DROP TYPE IF EXISTS ambiguous_item_status CASCADE;
        DROP TYPE IF EXISTS audit_event_type CASCADE;
        DROP TYPE IF EXISTS ownership_status CASCADE;
        DROP TYPE IF EXISTS evidence_review_status CASCADE;
        DROP TYPE IF EXISTS timeliness_status CASCADE;
        DROP TYPE IF EXISTS lifecycle_status CASCADE;
    """)
