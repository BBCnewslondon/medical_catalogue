import pytest
from sqlalchemy import text


def test_enums_exist_in_postgres(db_session):
    """Verify all 6 PostgreSQL native enum types exist and contain expected values."""
    query = text("""
        SELECT typname, enumlabel
        FROM pg_enum e
        JOIN pg_type t ON e.enumtypid = t.oid
        ORDER BY typname, enumsortorder;
    """)
    result = db_session.execute(query).fetchall()
    enums_map = {}
    for typname, label in result:
        enums_map.setdefault(typname, []).append(label)

    assert "lifecycle_status" in enums_map
    assert "DRAFT" in enums_map["lifecycle_status"]
    assert "SUPERSEDED" in enums_map["lifecycle_status"]
    assert "CANCELLED" in enums_map["lifecycle_status"]

    assert "timeliness_status" in enums_map
    assert set(enums_map["timeliness_status"]) == {"NOT_DUE", "DUE", "OVERDUE", "NOT_APPLICABLE"}

    assert "evidence_review_status" in enums_map
    assert "NO_EVIDENCE" in enums_map["evidence_review_status"]
    assert "VERIFIED_COMPLETE" in enums_map["evidence_review_status"]

    assert "ownership_status" in enums_map
    assert set(enums_map["ownership_status"]) == {"OWNED", "NO_OWNER"}

    assert "audit_event_type" in enums_map
    assert "CREATION" in enums_map["audit_event_type"]
    assert "STATE_CHANGE" in enums_map["audit_event_type"]
    assert "SUPERSEDED" in enums_map["audit_event_type"]

    assert "ambiguous_item_status" in enums_map
    assert set(enums_map["ambiguous_item_status"]) == {"OPEN", "RESOLVED", "OVERDUE"}


def test_compound_and_partial_indexes_exist(db_session):
    """Verify compound dimension index and partial active-risk index exist."""
    query = text("""
        SELECT indexname, indexdef
        FROM pg_indexes
        WHERE tablename = 'obligations';
    """)
    indexes = {row[0]: row[1] for row in db_session.execute(query).fetchall()}

    assert "idx_obligations_dimensions" in indexes
    assert "idx_obligations_active_risk" in indexes
    # Ensure partial index condition is present
    assert (
        "WHERE (lifecycle_status = 'ACTIVE'::lifecycle_status)"
        in indexes["idx_obligations_active_risk"]
    )


def test_raw_sql_check_constraints(raw_conn):
    """Verify raw SQL check constraints for due window, supersession, and relaxed ownership."""
    cursor = raw_conn.cursor()

    # 1. Due window check constraint: due_window_end < due_window_start must fail
    with pytest.raises(Exception) as excinfo:
        cursor.execute("""
            INSERT INTO obligations (
                patient_id, source_evidence, required_action_code, required_action_description,
                due_window_start, due_window_end, lifecycle_status, timeliness_status,
                evidence_review_status, ownership_status
            ) VALUES (
                'PAT-123', '{"doc": "discharge"}'::jsonb, 'U_AND_E', 'Check renal profile',
                '2026-10-10 10:00:00+00', '2026-10-09 10:00:00+00', 'DRAFT', 'NOT_DUE',
                'NO_EVIDENCE', 'NO_OWNER'
            );
        """)
    raw_conn.rollback()
    assert "chk_obligation_due_window" in str(excinfo.value)

    # 2. Ownership check constraint: OWNED with neither team nor user must fail
    with pytest.raises(Exception) as excinfo:
        cursor.execute("""
            INSERT INTO obligations (
                patient_id, source_evidence, required_action_code, required_action_description,
                due_window_end, lifecycle_status, timeliness_status,
                evidence_review_status, ownership_status, assigned_team, assigned_user_id
            ) VALUES (
                'PAT-123', '{"doc": "discharge"}'::jsonb, 'U_AND_E', 'Check renal profile',
                '2026-10-10 10:00:00+00', 'DRAFT', 'NOT_DUE',
                'NO_EVIDENCE', 'OWNED', NULL, NULL
            );
        """)
    raw_conn.rollback()
    assert "chk_obligation_ownership" in str(excinfo.value)

    # 3. Relaxed NO_OWNER constraint: NO_OWNER with assigned_team (e.g. Ward 4B) MUST succeed
    cursor.execute("""
        BEGIN;
        INSERT INTO obligations (
            id, patient_id, source_evidence, required_action_code, required_action_description,
            due_window_end, lifecycle_status, timeliness_status,
            evidence_review_status, ownership_status, assigned_team, assigned_user_id, audit_seq
        ) VALUES (
            'a0000000-0000-0000-0000-000000000001', 'PAT-123', '{"doc": "discharge"}'::jsonb,
            'U_AND_E', 'Check renal profile', '2026-10-10 10:00:00+00', 'DRAFT', 'NOT_DUE',
            'NO_EVIDENCE', 'NO_OWNER', 'Ward 4B Team', NULL, 1
        );
        INSERT INTO obligation_audit_log (
            obligation_id, audit_seq, event_type, actor_id, new_state, reason_code
        ) VALUES (
            'a0000000-0000-0000-0000-000000000001', 1, 'CREATION', 'SYSTEM',
            '{"lifecycle_status": "DRAFT"}'::jsonb, 'INITIAL_EXTRACTION'
        );
        COMMIT;
    """)

    # 4. Superseded constraint: SUPERSEDED with neither superseded_by_id nor migration_flag must fail
    with pytest.raises(Exception) as excinfo:
        cursor.execute("""
            INSERT INTO obligations (
                patient_id, source_evidence, required_action_code, required_action_description,
                due_window_end, lifecycle_status, timeliness_status,
                evidence_review_status, ownership_status, superseded_by_id, migration_flag
            ) VALUES (
                'PAT-123', '{"doc": "discharge"}'::jsonb, 'U_AND_E', 'Check renal profile',
                '2026-10-10 10:00:00+00', 'SUPERSEDED', 'NOT_DUE',
                'NO_EVIDENCE', 'NO_OWNER', NULL, NULL
            );
        """)
    raw_conn.rollback()
    assert "chk_obligation_superseded" in str(excinfo.value)
