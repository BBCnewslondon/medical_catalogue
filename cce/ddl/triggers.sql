-- ============================================================================
-- Clinical Completion Engine (CCE) - Safety & Audit Triggers
-- Checkpoint 1.1: Immutability, Anti-Deletion, and Deferred Audit Enforcement
-- ============================================================================

-- 1. PREVENT HARD DELETION ON OBLIGATIONS
-- ----------------------------------------------------------------------------
-- Clinical safety invariant: In healthcare operations, clinical obligations
-- must NEVER be silently deleted. Legitimate changes in clinical intention
-- must be documented as SUPERSEDED or CANCELLED with clinical rationale.
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


-- 2. IMMUTABILITY OF AUDIT LEDGER
-- ----------------------------------------------------------------------------
-- The obligation_audit_log is an append-only legal/clinical ledger.
-- Records cannot be modified or purged under any circumstances.
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


-- 3. AUDIT SEQUENCE INCREMENTATION ON OBLIGATION UPDATE
-- ----------------------------------------------------------------------------
-- Every update to an obligation increments audit_seq by 1 and updates updated_at.
-- This creates a strictly increasing monotonic version number that pairs 1-to-1
-- with an obligation_audit_log record having the identical audit_seq.
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


-- 4. DEFERRED MANDATORY AUDIT ENFORCEMENT
-- ----------------------------------------------------------------------------
-- Enforces that neither creation (audit_seq = 1) nor any subsequent update
-- (audit_seq = N) can commit without a corresponding audit log row matching
-- (obligation_id, audit_seq).
-- Because this is a DEFERRED CONSTRAINT TRIGGER, the audit record can be
-- inserted before or after the obligation mutation within the transaction.
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

