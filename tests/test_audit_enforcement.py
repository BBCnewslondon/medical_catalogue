from datetime import UTC, datetime

import pytest

from cce.audit import AuditMissingError, ImmutabilityViolationError
from cce.enums import (
    LifecycleStatus,
)
from cce.models import Obligation
from cce.service import ObligationService


def test_insert_obligation_without_audit_log_fails_in_orm(db_session):
    """Verify ORM before_flush rejects inserting an Obligation without a creation audit log."""
    due_end = datetime(2026, 11, 1, 12, 0, tzinfo=UTC)
    ob = Obligation(
        patient_id="PAT-NO-AUDIT",
        source_evidence={"doc": "Discharge Summary"},
        required_action_code="ECG",
        required_action_description="Repeat 12-lead ECG",
        due_window_end=due_end,
        audit_seq=1,
    )
    db_session.add(ob)

    with pytest.raises(AuditMissingError) as excinfo:
        db_session.flush()

    assert "lacks required creation audit log" in str(excinfo.value)


def test_insert_obligation_without_audit_log_fails_in_raw_sql(raw_conn):
    """Verify PostgreSQL deferred constraint trigger rejects INSERT without audit log at commit."""
    cursor = raw_conn.cursor()
    cursor.execute("BEGIN;")

    cursor.execute("""
        INSERT INTO obligations (
            id, patient_id, source_evidence, required_action_code, required_action_description,
            due_window_end, lifecycle_status, timeliness_status, evidence_review_status,
            ownership_status, audit_seq
        ) VALUES (
            'b0000000-0000-0000-0000-000000000001', 'PAT-RAW-INSERT', '{"doc": "text"}'::jsonb,
            'ECG', 'Repeat ECG', '2026-11-01 12:00:00+00', 'DRAFT', 'NOT_DUE', 'NO_EVIDENCE',
            'NO_OWNER', 1
        );
    """)

    # Attempting to COMMIT without inserting an audit log must fail
    with pytest.raises(Exception) as excinfo:
        cursor.execute("COMMIT;")

    raw_conn.rollback()
    assert "trg_enforce_audit_on_mutation" in str(excinfo.value) or "Audit violation" in str(
        excinfo.value
    )


def test_update_obligation_without_audit_log_fails_in_orm(db_session):
    """Verify ORM before_flush rejects updating an Obligation without a staged audit log."""
    due_end = datetime(2026, 11, 1, 12, 0, tzinfo=UTC)

    # 1. Create obligation safely
    ob = ObligationService.create_obligation(
        session=db_session,
        patient_id="PAT-DIRTY-TEST",
        source_evidence={"doc": "Discharge"},
        required_action_code="MRI_BRAIN",
        required_action_description="Repeat MRI brain in 4 weeks",
        due_window_end=due_end,
    )
    db_session.flush()

    # 2. Modify obligation directly without creating an audit log
    ob.lifecycle_status = LifecycleStatus.ACTIVE

    with pytest.raises(AuditMissingError) as excinfo:
        db_session.flush()

    assert "updated without required audit log" in str(excinfo.value)


def test_update_obligation_without_audit_log_fails_in_raw_sql(raw_conn):
    """Verify PostgreSQL deferred constraint trigger rejects direct SQL UPDATE without audit log."""
    cursor = raw_conn.cursor()

    # Create obligation with proper creation audit
    cursor.execute("""
        BEGIN;
        INSERT INTO obligations (
            id, patient_id, source_evidence, required_action_code, required_action_description,
            due_window_end, lifecycle_status, timeliness_status, evidence_review_status,
            ownership_status, audit_seq
        ) VALUES (
            'b0000000-0000-0000-0000-000000000002', 'PAT-RAW-UPDATE', '{"doc": "text"}'::jsonb,
            'MRI', 'Repeat MRI', '2026-11-01 12:00:00+00', 'DRAFT', 'NOT_DUE', 'NO_EVIDENCE',
            'NO_OWNER', 1
        );
        INSERT INTO obligation_audit_log (
            obligation_id, audit_seq, event_type, actor_id, new_state, reason_code
        ) VALUES (
            'b0000000-0000-0000-0000-000000000002', 1, 'CREATION', 'SYSTEM',
            '{"lifecycle_status": "DRAFT"}'::jsonb, 'INITIAL_EXTRACTION'
        );
        COMMIT;
    """)

    # Now attempt direct SQL update without audit log
    cursor.execute("BEGIN;")
    cursor.execute("""
        UPDATE obligations
        SET lifecycle_status = 'ACTIVE'
        WHERE id = 'b0000000-0000-0000-0000-000000000002';
    """)

    with pytest.raises(Exception) as excinfo:
        cursor.execute("COMMIT;")

    raw_conn.rollback()
    assert "trg_enforce_audit_on_mutation" in str(excinfo.value) or "Audit violation" in str(
        excinfo.value
    )


def test_multiple_updates_in_single_transaction_require_individual_audits(raw_conn):
    """Verify defensive audit_seq tracking: 2 updates in 1 transaction require 2 distinct audits."""
    cursor = raw_conn.cursor()

    # Step 1: Initial insertion
    cursor.execute("""
        BEGIN;
        INSERT INTO obligations (
            id, patient_id, source_evidence, required_action_code, required_action_description,
            due_window_end, lifecycle_status, timeliness_status, evidence_review_status,
            ownership_status, audit_seq
        ) VALUES (
            'b0000000-0000-0000-0000-000000000003', 'PAT-MULTI-UPDATE', '{"doc": "clinic"}'::jsonb,
            'ECHO', 'Repeat Echo', '2026-11-01 12:00:00+00', 'DRAFT', 'NOT_DUE', 'NO_EVIDENCE',
            'NO_OWNER', 1
        );
        INSERT INTO obligation_audit_log (
            obligation_id, audit_seq, event_type, actor_id, new_state, reason_code
        ) VALUES (
            'b0000000-0000-0000-0000-000000000003', 1, 'CREATION', 'SYSTEM',
            '{"lifecycle_status": "DRAFT"}'::jsonb, 'INITIAL_EXTRACTION'
        );
        COMMIT;
    """)

    # Step 2: In a single transaction, perform two updates.
    # If we only insert an audit for seq=2 and NOT for seq=3, commit must fail.
    cursor.execute("BEGIN;")
    cursor.execute("""
        UPDATE obligations
        SET lifecycle_status = 'ACTIVE'
        WHERE id = 'b0000000-0000-0000-0000-000000000003';
    """)
    cursor.execute("""
        INSERT INTO obligation_audit_log (
            obligation_id, audit_seq, event_type, actor_id, new_state, reason_code
        ) VALUES (
            'b0000000-0000-0000-0000-000000000003', 2, 'STATE_CHANGE', 'DR_CARDIOLOGY',
            '{"lifecycle_status": "ACTIVE"}'::jsonb, 'PLAN_CONFIRMED'
        );
    """)

    # Second update in SAME transaction: audit_seq becomes 3
    cursor.execute("""
        UPDATE obligations
        SET timeliness_status = 'DUE'
        WHERE id = 'b0000000-0000-0000-0000-000000000003';
    """)

    with pytest.raises(Exception) as excinfo:
        cursor.execute("COMMIT;")
    raw_conn.rollback()
    assert "audit_seq 3" in str(excinfo.value) or "trg_enforce_audit_on_mutation" in str(
        excinfo.value
    )

    # Now verify that providing BOTH audits for seq 2 and seq 3 succeeds
    cursor.execute("BEGIN;")
    cursor.execute("""
        UPDATE obligations
        SET lifecycle_status = 'ACTIVE'
        WHERE id = 'b0000000-0000-0000-0000-000000000003';
    """)
    cursor.execute("""
        INSERT INTO obligation_audit_log (
            obligation_id, audit_seq, event_type, actor_id, new_state, reason_code
        ) VALUES (
            'b0000000-0000-0000-0000-000000000003', 2, 'STATE_CHANGE', 'DR_CARDIOLOGY',
            '{"lifecycle_status": "ACTIVE"}'::jsonb, 'PLAN_CONFIRMED'
        );
    """)
    cursor.execute("""
        UPDATE obligations
        SET timeliness_status = 'DUE'
        WHERE id = 'b0000000-0000-0000-0000-000000000003';
    """)
    cursor.execute("""
        INSERT INTO obligation_audit_log (
            obligation_id, audit_seq, event_type, actor_id, new_state, reason_code
        ) VALUES (
            'b0000000-0000-0000-0000-000000000003', 3, 'STATE_CHANGE', 'SYSTEM_TIMER',
            '{"timeliness_status": "DUE"}'::jsonb, 'WINDOW_ENTERED'
        );
    """)
    cursor.execute("COMMIT;")

    cursor.execute(
        "SELECT count(*) FROM obligation_audit_log WHERE obligation_id = 'b0000000-0000-0000-0000-000000000003';"
    )
    count = cursor.fetchone()[0]
    assert count == 3


def test_prohibit_hard_deletion_on_obligations_orm(db_session):
    """Verify direct hard DELETE on obligations is strictly blocked in ORM before_flush."""
    due_end = datetime(2026, 11, 1, 12, 0, tzinfo=UTC)
    ob = ObligationService.create_obligation(
        session=db_session,
        patient_id="PAT-NO-DELETE-ORM",
        source_evidence={"doc": "Discharge"},
        required_action_code="HBA1C",
        required_action_description="Diabetes HbA1c check",
        due_window_end=due_end,
    )
    db_session.flush()

    with pytest.raises(ImmutabilityViolationError) as excinfo:
        db_session.delete(ob)
        db_session.flush()
    assert "Direct deletion of obligation" in str(excinfo.value)


def test_prohibit_hard_deletion_on_obligations_raw_sql(raw_conn):
    """Verify direct hard DELETE on obligations is strictly blocked by PostgreSQL trigger."""
    cursor = raw_conn.cursor()
    cursor.execute("""
        BEGIN;
        INSERT INTO obligations (
            id, patient_id, source_evidence, required_action_code, required_action_description,
            due_window_end, lifecycle_status, timeliness_status, evidence_review_status,
            ownership_status, audit_seq
        ) VALUES (
            'b0000000-0000-0000-0000-000000000004', 'PAT-NO-DELETE-SQL', '{"doc": "discharge"}'::jsonb,
            'HBA1C', 'HbA1c check', '2026-11-01 12:00:00+00', 'DRAFT', 'NOT_DUE', 'NO_EVIDENCE',
            'NO_OWNER', 1
        );
        INSERT INTO obligation_audit_log (
            obligation_id, audit_seq, event_type, actor_id, new_state, reason_code
        ) VALUES (
            'b0000000-0000-0000-0000-000000000004', 1, 'CREATION', 'SYSTEM',
            '{"lifecycle_status": "DRAFT"}'::jsonb, 'INITIAL_EXTRACTION'
        );
        COMMIT;
    """)

    with pytest.raises(Exception) as excinfo:
        cursor.execute("DELETE FROM obligations WHERE id = 'b0000000-0000-0000-0000-000000000004';")

    raw_conn.rollback()
    assert (
        "Clinical safety violation: Direct deletion of obligations is strictly prohibited"
        in str(excinfo.value)
    )


def test_prohibit_mutation_or_deletion_on_audit_log_raw_sql(raw_conn):
    """Verify obligation_audit_log is append-only; updates and deletes are blocked by trigger."""
    cursor = raw_conn.cursor()
    cursor.execute("""
        BEGIN;
        INSERT INTO obligations (
            id, patient_id, source_evidence, required_action_code, required_action_description,
            due_window_end, lifecycle_status, timeliness_status, evidence_review_status,
            ownership_status, audit_seq
        ) VALUES (
            'b0000000-0000-0000-0000-000000000005', 'PAT-AUDIT-IMMUTABLE-SQL', '{"doc": "discharge"}'::jsonb,
            'HBA1C', 'HbA1c check', '2026-11-01 12:00:00+00', 'DRAFT', 'NOT_DUE', 'NO_EVIDENCE',
            'NO_OWNER', 1
        );
        INSERT INTO obligation_audit_log (
            id, obligation_id, audit_seq, event_type, actor_id, new_state, reason_code
        ) VALUES (
            'c0000000-0000-0000-0000-000000000001', 'b0000000-0000-0000-0000-000000000005', 1, 'CREATION', 'SYSTEM',
            '{"lifecycle_status": "DRAFT"}'::jsonb, 'INITIAL_EXTRACTION'
        );
        COMMIT;
    """)

    # 1. Test update via raw SQL
    with pytest.raises(Exception) as excinfo:
        cursor.execute(
            "UPDATE obligation_audit_log SET reason_code = 'ALTERED' WHERE id = 'c0000000-0000-0000-0000-000000000001';"
        )
    raw_conn.rollback()
    assert "Audit ledger violation: obligation_audit_log is append-only" in str(excinfo.value)

    # 2. Test delete via raw SQL
    with pytest.raises(Exception) as excinfo:
        cursor.execute(
            "DELETE FROM obligation_audit_log WHERE id = 'c0000000-0000-0000-0000-000000000001';"
        )
    raw_conn.rollback()
    assert "Audit ledger violation: obligation_audit_log is append-only" in str(excinfo.value)


def test_prohibit_deletion_on_audit_log_orm(db_session):
    """Verify obligation_audit_log deletion is blocked in ORM before_flush."""
    due_end = datetime(2026, 11, 1, 12, 0, tzinfo=UTC)
    ob = ObligationService.create_obligation(
        session=db_session,
        patient_id="PAT-AUDIT-IMMUTABLE-ORM-DEL",
        source_evidence={"doc": "Discharge"},
        required_action_code="HBA1C",
        required_action_description="Diabetes HbA1c check",
        due_window_end=due_end,
    )
    db_session.flush()
    audit_entry = ob.audit_logs[0]

    with pytest.raises(ImmutabilityViolationError) as excinfo:
        db_session.delete(audit_entry)
        db_session.flush()
    assert "Deletions from obligation_audit_log" in str(excinfo.value)


def test_prohibit_update_on_audit_log_orm(db_session):
    """Verify obligation_audit_log update is blocked in ORM before_flush."""
    due_end = datetime(2026, 11, 1, 12, 0, tzinfo=UTC)
    ob = ObligationService.create_obligation(
        session=db_session,
        patient_id="PAT-AUDIT-IMMUTABLE-ORM-UPD",
        source_evidence={"doc": "Discharge"},
        required_action_code="HBA1C",
        required_action_description="Diabetes HbA1c check",
        due_window_end=due_end,
    )
    db_session.flush()
    audit_entry = ob.audit_logs[0]

    audit_entry.reason_code = "ALTERED_BY_ORM"
    with pytest.raises(ImmutabilityViolationError) as excinfo:
        db_session.flush()
    assert "Updates to obligation_audit_log" in str(excinfo.value)
