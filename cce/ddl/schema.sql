-- ============================================================================
-- Clinical Completion Engine (CCE) - Foundational Schema
-- Checkpoint 1.1: Core Schemas, Enums, Tables, Constraints & Indexes
-- ============================================================================

-- 1. ENUMERATIONS & STATE DIMENSIONS
-- ----------------------------------------------------------------------------

DO $$ BEGIN
    CREATE TYPE lifecycle_status AS ENUM (
        'DRAFT',
        'CONFIRMED',
        'ACTIVE',
        'COMPLETE',
        'CANCEL_REQUESTED',
        'CANCELLED',
        'SUPERSEDED',
        'INVALID'
    );
EXCEPTION
    WHEN duplicate_object THEN null;
END $$;

DO $$ BEGIN
    CREATE TYPE timeliness_status AS ENUM (
        'NOT_DUE',
        'DUE',
        'OVERDUE',
        'NOT_APPLICABLE'
    );
EXCEPTION
    WHEN duplicate_object THEN null;
END $$;

DO $$ BEGIN
    CREATE TYPE evidence_review_status AS ENUM (
        'NO_EVIDENCE',
        'ACTION_EVIDENCE_RECEIVED',
        'AWAITING_REVIEW_EVIDENCE',
        'AMBIGUOUS_REVIEW_EVIDENCE',
        'VERIFIED_COMPLETE'
    );
EXCEPTION
    WHEN duplicate_object THEN null;
END $$;

DO $$ BEGIN
    CREATE TYPE ownership_status AS ENUM (
        'OWNED',
        'NO_OWNER'
    );
EXCEPTION
    WHEN duplicate_object THEN null;
END $$;

DO $$ BEGIN
    CREATE TYPE audit_event_type AS ENUM (
        'CREATION',
        'STATE_CHANGE',
        'MANUAL_OVERRIDE',
        'CANCELLATION',
        'SUPERSEDED',
        'OWNERSHIP_ASSIGNED',
        'CONFIRMATION'
    );
EXCEPTION
    WHEN duplicate_object THEN null;
END $$;

DO $$ BEGIN
    CREATE TYPE ambiguous_item_status AS ENUM (
        'OPEN',
        'RESOLVED',
        'OVERDUE'
    );
EXCEPTION
    WHEN duplicate_object THEN null;
END $$;


-- 2. CORE TABLES
-- ----------------------------------------------------------------------------

-- Table: obligations (Primary Clinical Obligation Entity)
CREATE TABLE IF NOT EXISTS obligations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    patient_id TEXT NOT NULL,
    source_evidence JSONB NOT NULL,
    required_action_code VARCHAR(128) NOT NULL,
    required_action_description TEXT NOT NULL,
    due_window_start TIMESTAMPTZ,
    due_window_end TIMESTAMPTZ NOT NULL,
    
    -- 4 Independent State Dimensions
    lifecycle_status lifecycle_status NOT NULL DEFAULT 'DRAFT',
    timeliness_status timeliness_status NOT NULL DEFAULT 'NOT_DUE',
    evidence_review_status evidence_review_status NOT NULL DEFAULT 'NO_EVIDENCE',
    ownership_status ownership_status NOT NULL DEFAULT 'NO_OWNER',
    
    -- Accountable Owners
    assigned_team TEXT,
    assigned_user_id TEXT,
    
    -- Supersession Pointer & Plan Change Context
    superseded_by_id UUID REFERENCES obligations(id) ON DELETE RESTRICT,
    migration_flag TEXT,
    
    -- Audit Sequence Tracking (strict 1-to-1 event pairing)
    audit_seq INTEGER NOT NULL DEFAULT 1,
    
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),

    -- Constraints
    CONSTRAINT chk_obligation_superseded CHECK (
        lifecycle_status != 'SUPERSEDED' OR (superseded_by_id IS NOT NULL OR migration_flag IS NOT NULL)
    ),
    CONSTRAINT chk_obligation_ownership CHECK (
        (ownership_status != 'OWNED') OR (assigned_team IS NOT NULL OR assigned_user_id IS NOT NULL)
    ),
    CONSTRAINT chk_obligation_due_window CHECK (
        due_window_start IS NULL OR due_window_end >= due_window_start
    )
);

-- Table: obligation_audit_log (Append-only immutable event store)
CREATE TABLE IF NOT EXISTS obligation_audit_log (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    obligation_id UUID NOT NULL REFERENCES obligations(id) ON DELETE RESTRICT,
    audit_seq INTEGER NOT NULL,
    event_type audit_event_type NOT NULL,
    actor_id TEXT NOT NULL,
    previous_state JSONB,
    new_state JSONB NOT NULL,
    reason_code VARCHAR(128) NOT NULL,
    rationale_text TEXT,
    evidence_reference JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
);

-- Table: ambiguous_review_items (Queue for ambiguous evidence matching)
CREATE TABLE IF NOT EXISTS ambiguous_review_items (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    obligation_id UUID NOT NULL REFERENCES obligations(id) ON DELETE RESTRICT,
    proposed_evidence_snippet JSONB NOT NULL,
    assigned_reviewer_id TEXT,
    due_at TIMESTAMPTZ NOT NULL,
    status ambiguous_item_status NOT NULL DEFAULT 'OPEN',
    resolution_rationale TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
);


-- 3. INDEXES
-- ----------------------------------------------------------------------------

-- Patient queries
CREATE INDEX IF NOT EXISTS idx_obligations_patient_id 
    ON obligations (patient_id);

-- Compound index on all 4 independent dimensions
CREATE INDEX IF NOT EXISTS idx_obligations_dimensions 
    ON obligations (lifecycle_status, timeliness_status, evidence_review_status, ownership_status);

-- Partial index for clinical active-risk monitoring queries
CREATE INDEX IF NOT EXISTS idx_obligations_active_risk 
    ON obligations (timeliness_status, ownership_status) 
    WHERE lifecycle_status = 'ACTIVE';

-- Supersession hierarchy indexing
CREATE INDEX IF NOT EXISTS idx_obligations_superseded_by 
    ON obligations (superseded_by_id);

-- Audit log indexes for rapid sequence lookup and history reconstruction
CREATE INDEX IF NOT EXISTS idx_audit_log_obligation_seq 
    ON obligation_audit_log (obligation_id, audit_seq);

CREATE INDEX IF NOT EXISTS idx_audit_log_obligation_created 
    ON obligation_audit_log (obligation_id, created_at);

-- Ambiguous review queue queries
CREATE INDEX IF NOT EXISTS idx_ambiguous_items_obligation_id 
    ON ambiguous_review_items (obligation_id);

CREATE INDEX IF NOT EXISTS idx_ambiguous_items_status 
    ON ambiguous_review_items (status);

