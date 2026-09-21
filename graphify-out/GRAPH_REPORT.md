# Graph Report - medical_catalogue  (2026-09-21)

## Corpus Check
- Corpus is ~8,294 words - fits in a single context window. You may not need a graph.

## Summary
- 154 nodes · 386 edges · 16 communities (13 shown, 3 thin omitted)
- Extraction: 84% EXTRACTED · 16% INFERRED · 0% AMBIGUOUS · INFERRED: 62 edges (avg confidence: 0.95)
- Token cost: 0 input · 0 output

## Community Hubs (Navigation)
- Core ORM and Audit
- Audit Enforcement Tests
- Architecture and CI
- Migration Pipeline
- Supersession Semantics
- Ownership Services
- Obligation Creation
- Dimension Updates
- Service Actions
- Raw SQL Tests
- Database Fixtures
- Ownership Constraints
- Graphify Guidance
- Dimension Snapshots
- Developer Checks
- Package Export

## God Nodes (most connected - your core abstractions)
1. `ObligationService` - 31 edges
2. `Obligation` - 28 edges
3. `AuditEventType` - 23 edges
4. `LifecycleStatus` - 19 edges
5. `OwnershipStatus` - 18 edges
6. `ObligationAuditLog` - 17 edges
7. `TimelinessStatus` - 16 edges
8. `EvidenceReviewStatus` - 16 edges
9. `test_insert_complete_obligation_with_four_dimensions()` - 10 edges
10. `build_audit_log()` - 9 edges

## Surprising Connections (you probably didn't know these)
- `NHS-Realistic Ownership Constraints` --references--> `Obligation`  [EXTRACTED]
  README.md → cce/models.py
- `Supersession vs Cancellation` --references--> `Domain Service Operations`  [INFERRED]
  README.md → cce/service.py
- `test_update_obligation_without_audit_log_fails_in_orm()` --uses--> `LifecycleStatus`  [INFERRED]
  tests/test_audit_enforcement.py → cce/enums.py
- `test_insert_complete_obligation_with_four_dimensions()` --uses--> `LifecycleStatus`  [INFERRED]
  tests/test_models.py → cce/enums.py
- `test_invalid_ownership_raises_integrity_error()` --uses--> `LifecycleStatus`  [INFERRED]
  tests/test_models.py → cce/enums.py

## Import Cycles
- None detected.

## Communities (16 total, 3 thin omitted)

### Community 0 - "Core ORM and Audit"
Cohesion: 0.12
Nodes (28): AuditViolationError, build_audit_log(), InvalidStateTransitionError, Any, Base exception for audit and governance violations., Raised when an illegal state machine transition is attempted., Build an ObligationAuditLog entry paired to an obligation's current or target…, Register SQLAlchemy Session-level event listeners to enforce defensive audit… (+20 more)

### Community 1 - "Audit Enforcement Tests"
Cohesion: 0.11
Nodes (21): AuditMissingError, ImmutabilityViolationError, Raised when an obligation mutation lacks a corresponding audit log entry., Raised when an operation attempts to mutate or delete immutable clinical…, _enforce_audit_invariants_before_flush(), sqlalchemy_exc, Verify defensive audit_seq tracking: 2 updates in 1 transaction require 2…, Verify ORM before_flush rejects inserting an Obligation without a creation… (+13 more)

### Community 2 - "Architecture and CI"
Cohesion: 0.13
Nodes (15): Audit Enforcement, Domain Service Operations, CCE PostgreSQL Service, CI/CD Pipeline, Lint and Typecheck Job, Semantic Release, Test and Migrations Job, Pre-commit Hooks (+7 more)

### Community 3 - "Migration Pipeline"
Cohesion: 0.22
Nodes (7): alembic, logging_config, get_url(), run_migrations_offline(), run_migrations_online(), os, sqlalchemy_dialects

### Community 4 - "Supersession Semantics"
Cohesion: 0.29
Nodes (10): AuditEventType, LifecycleStatus, Class of audit event logged in immutable obligation audit ledger., Lifecycle progression dimension for a clinical obligation., Verify administrative cancellation is kept distinct from clinical supersession., Verify superseding an obligation by linking to a replacement obligation., Verify superseding an obligation using a structured migration flag (e.g.…, test_administrative_cancellation_vs_supersession() (+2 more)

### Community 5 - "Ownership Services"
Cohesion: 0.38
Nodes (6): OwnershipStatus, Clinical responsibility and accountability dimension., datetime, enum, Verify ObligationService.assign_owner allocates clinician ownership and creates…, test_assign_owner_service()

### Community 6 - "Obligation Creation"
Cohesion: 0.27
Nodes (9): ObligationService, Safe, auditable transactional service operations for Clinical Obligations., Create and ingest a new clinical obligation with its mandatory CREATION audit…, Validate inserting a complete obligation with all 4 independent dimensions., Validate NHS clinical reality: NO_OWNER can retain assigned_team context (e.g.…, test_insert_complete_obligation_with_four_dimensions(), test_relaxed_ownership_constraint_in_models(), Verify build_audit_log helper produces a valid ObligationAuditLog instance. (+1 more)

### Community 7 - "Dimension Updates"
Cohesion: 0.31
Nodes (8): EvidenceReviewStatus, Timeliness dimension relative to clinical deadline window., Evidence reconciliation and clinical review dimension., TimelinessStatus, Atomically update state dimensions and record a corresponding audit log., StrEnum, Verify ObligationService.update_dimensions updates fields and logs an audit…, test_update_dimensions_service()

### Community 8 - "Service Actions"
Cohesion: 0.29
Nodes (5): Any, Session, Transition an obligation to SUPERSEDED and link it to replacement or migration…, Administratively cancel an obligation with clinical rationale., Assign or update accountable clinical owner.

### Community 9 - "Raw SQL Tests"
Cohesion: 0.25
Nodes (7): pytest, Verify compound dimension index and partial active-risk index exist., Verify all 6 PostgreSQL native enum types exist and contain expected values., Verify raw SQL check constraints for due window, supersession, and relaxed…, test_compound_and_partial_indexes_exist(), test_enums_exist_in_postgres(), test_raw_sql_check_constraints()

### Community 10 - "Database Fixtures"
Cohesion: 0.33
Nodes (6): fixture, db_session(), Session, Function-scoped SQLAlchemy Session with automatic teardown., Raw DBAPI connection for verifying direct SQL triggers and invariants., raw_conn()

### Community 11 - "Ownership Constraints"
Cohesion: 0.50
Nodes (4): Obligation, Primary clinical obligation entity. Tracks four independent state dimensions…, Validate that OWNED without assigned_team or assigned_user_id violates…, test_invalid_ownership_raises_integrity_error()

### Community 12 - "Graphify Guidance"
Cohesion: 0.67
Nodes (3): Graphify Knowledge Graph Rule, Graphify Pipeline Workflow, Graphify Repository Workflow

## Knowledge Gaps
- **9 isolated node(s):** `medical_catalogue_cce`, `check.sh script`, `Semantic Release`, `Pre-commit Hooks`, `CCE PostgreSQL Service` (+4 more)
  These have ≤1 connection - possible missing edges or undocumented components. (Counts symbols only; 67 node(s) total have ≤1 connection when file, concept and rationale nodes are included.)
- **3 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `Obligation` connect `Ownership Constraints` to `Core ORM and Audit`, `Audit Enforcement Tests`, `Architecture and CI`, `Supersession Semantics`, `Ownership Services`, `Obligation Creation`, `Dimension Updates`, `Service Actions`, `Dimension Snapshots`?**
  _High betweenness centrality (0.270) - this node is a cross-community bridge._
- **Why does `NHS-Realistic Ownership Constraints` connect `Architecture and CI` to `Ownership Constraints`?**
  _High betweenness centrality (0.160) - this node is a cross-community bridge._
- **Are the 19 inferred relationships involving `ObligationService` (e.g. with `AuditEventType` and `EvidenceReviewStatus`) actually correct?**
  _`ObligationService` has 19 INFERRED edges - model-reasoned connections that need verification._
- **Are the 10 inferred relationships involving `Obligation` (e.g. with `build_audit_log()` and `register_audit_listeners()`) actually correct?**
  _`Obligation` has 10 INFERRED edges - model-reasoned connections that need verification._
- **Are the 11 inferred relationships involving `AuditEventType` (e.g. with `build_audit_log()` and `ObligationAuditLog`) actually correct?**
  _`AuditEventType` has 11 INFERRED edges - model-reasoned connections that need verification._
- **Are the 8 inferred relationships involving `LifecycleStatus` (e.g. with `Obligation` and `ObligationService`) actually correct?**
  _`LifecycleStatus` has 8 INFERRED edges - model-reasoned connections that need verification._
- **Are the 6 inferred relationships involving `OwnershipStatus` (e.g. with `Obligation` and `ObligationService`) actually correct?**
  _`OwnershipStatus` has 6 INFERRED edges - model-reasoned connections that need verification._