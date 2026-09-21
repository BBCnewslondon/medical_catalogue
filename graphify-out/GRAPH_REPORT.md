# Graph Report - medical_catalogue  (2026-09-21)

## Corpus Check
- 21 files · ~8,437 words
- Verdict: corpus is large enough that graph structure adds value.
- Unclassified: 3 file(s) not represented in the graph (top: (none) 1, .ini 1, .mako 1)

## Summary
- 161 nodes · 386 edges · 13 communities (10 shown, 3 thin omitted)
- Extraction: 83% EXTRACTED · 17% INFERRED · 0% AMBIGUOUS · INFERRED: 65 edges (avg confidence: 0.95)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `1828559b`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- __init__.py
- test_audit_enforcement.py
- Clinical Completion Engine
- conftest.py
- .create_obligation
- models.py
- ObligationService
- EvidenceReviewStatus
- Obligation
- Graphify Repository Workflow
- .get_dimensions_snapshot
- check.sh
- medical_catalogue_cce

## God Nodes (most connected - your core abstractions)
1. `ObligationService` - 32 edges
2. `Obligation` - 28 edges
3. `AuditEventType` - 22 edges
4. `LifecycleStatus` - 19 edges
5. `OwnershipStatus` - 17 edges
6. `ObligationAuditLog` - 16 edges
7. `TimelinessStatus` - 15 edges
8. `EvidenceReviewStatus` - 15 edges
9. `test_insert_complete_obligation_with_four_dimensions()` - 10 edges
10. `ImmutabilityViolationError` - 9 edges

## Surprising Connections (you probably didn't know these)
- `NHS-Realistic Ownership Constraints` --references--> `Obligation`  [EXTRACTED]
  README.md → cce/models.py
- `Supersession vs Cancellation` --references--> `Domain Service Operations`  [INFERRED]
  README.md → cce/service.py
- `test_insert_obligation_without_audit_log_fails_in_orm()` --uses--> `AuditMissingError`  [INFERRED]
  tests/test_audit_enforcement.py → cce/audit.py
- `test_update_obligation_without_audit_log_fails_in_orm()` --uses--> `AuditMissingError`  [INFERRED]
  tests/test_audit_enforcement.py → cce/audit.py
- `test_prohibit_deletion_on_audit_log_orm()` --uses--> `ImmutabilityViolationError`  [INFERRED]
  tests/test_audit_enforcement.py → cce/audit.py

## Import Cycles
- None detected.

## Communities (13 total, 3 thin omitted)

### Community 0 - "__init__.py"
Cohesion: 0.16
Nodes (20): AuditMissingError, AuditViolationError, build_audit_log(), ImmutabilityViolationError, InvalidStateTransitionError, Any, Base exception for audit and governance violations., Raised when an obligation mutation lacks a corresponding audit log entry. (+12 more)

### Community 1 - "test_audit_enforcement.py"
Cohesion: 0.11
Nodes (18): Verify defensive audit_seq tracking: 2 updates in 1 transaction require 2…, Verify ORM before_flush rejects inserting an Obligation without a creation…, Verify direct hard DELETE on obligations is strictly blocked in ORM…, Verify direct hard DELETE on obligations is strictly blocked by PostgreSQL…, Verify obligation_audit_log is append-only; updates and deletes are blocked by…, Verify obligation_audit_log deletion is blocked in ORM before_flush., Verify PostgreSQL deferred constraint trigger rejects INSERT without audit log…, Verify obligation_audit_log update is blocked in ORM before_flush. (+10 more)

### Community 2 - "Clinical Completion Engine"
Cohesion: 0.13
Nodes (15): Audit Enforcement, Domain Service Operations, CCE PostgreSQL Service, CI/CD Pipeline, Lint and Typecheck Job, Semantic Release, Test and Migrations Job, Pre-commit Hooks (+7 more)

### Community 3 - "conftest.py"
Cohesion: 0.08
Nodes (25): alembic, collections_abc, fixture, logging_config, get_url(), run_migrations_offline(), run_migrations_online(), os (+17 more)

### Community 4 - ".create_obligation"
Cohesion: 0.24
Nodes (11): LifecycleStatus, Lifecycle progression dimension for a clinical obligation., Create and ingest a new clinical obligation with its mandatory CREATION audit…, Verify ORM before_flush rejects updating an Obligation without a staged audit…, test_update_obligation_without_audit_log_fails_in_orm(), Verify administrative cancellation is kept distinct from clinical supersession., Verify superseding an obligation by linking to a replacement obligation., Verify superseding an obligation using a structured migration flag (e.g.… (+3 more)

### Community 5 - "models.py"
Cohesion: 0.19
Nodes (17): AmbiguousItemStatus, OwnershipStatus, Clinical responsibility and accountability dimension., Status of an ambiguous evidence review queue item., AmbiguousReviewItem, Review queue entity for ambiguous evidence matching requiring clinical…, datetime, enum (+9 more)

### Community 6 - "ObligationService"
Cohesion: 0.31
Nodes (10): AuditEventType, Class of audit event logged in immutable obligation audit ledger., ObligationService, Safe, auditable transactional service operations for Clinical Obligations., Verify ObligationService.update_dimensions updates fields and logs an audit…, Verify ObligationService.assign_owner allocates clinician ownership and creates…, Verify build_audit_log helper produces a valid ObligationAuditLog instance., test_assign_owner_service() (+2 more)

### Community 7 - "EvidenceReviewStatus"
Cohesion: 0.28
Nodes (9): EvidenceReviewStatus, Timeliness dimension relative to clinical deadline window., Evidence reconciliation and clinical review dimension., TimelinessStatus, StrEnum, Validate inserting a complete obligation with all 4 independent dimensions., Validate that OWNED without assigned_team or assigned_user_id violates…, test_insert_complete_obligation_with_four_dimensions() (+1 more)

### Community 8 - "Obligation"
Cohesion: 0.24
Nodes (8): Obligation, Primary clinical obligation entity. Tracks four independent state dimensions…, Any, Session, Transition an obligation to SUPERSEDED and link it to replacement or migration…, Administratively cancel an obligation with clinical rationale., Assign or update accountable clinical owner., Atomically update state dimensions and record a corresponding audit log.

### Community 12 - "Graphify Repository Workflow"
Cohesion: 0.67
Nodes (3): Graphify Knowledge Graph Rule, Graphify Pipeline Workflow, Graphify Repository Workflow

## Knowledge Gaps
- **9 isolated node(s):** `medical_catalogue_cce`, `check.sh script`, `Graphify Knowledge Graph Rule`, `Graphify Pipeline Workflow`, `Audit Enforcement` (+4 more)
  These have ≤1 connection - possible missing edges or undocumented components. (Counts symbols only; 72 node(s) total have ≤1 connection when file, concept and rationale nodes are included.)
- **3 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `Obligation` connect `Obligation` to `__init__.py`, `test_audit_enforcement.py`, `Clinical Completion Engine`, `.create_obligation`, `models.py`, `ObligationService`, `EvidenceReviewStatus`, `.get_dimensions_snapshot`?**
  _High betweenness centrality (0.272) - this node is a cross-community bridge._
- **Why does `NHS-Realistic Ownership Constraints` connect `Clinical Completion Engine` to `Obligation`?**
  _High betweenness centrality (0.154) - this node is a cross-community bridge._
- **Are the 20 inferred relationships involving `ObligationService` (e.g. with `AuditEventType` and `EvidenceReviewStatus`) actually correct?**
  _`ObligationService` has 20 INFERRED edges - model-reasoned connections that need verification._
- **Are the 10 inferred relationships involving `Obligation` (e.g. with `build_audit_log()` and `register_audit_listeners()`) actually correct?**
  _`Obligation` has 10 INFERRED edges - model-reasoned connections that need verification._
- **Are the 11 inferred relationships involving `AuditEventType` (e.g. with `build_audit_log()` and `ObligationAuditLog`) actually correct?**
  _`AuditEventType` has 11 INFERRED edges - model-reasoned connections that need verification._
- **Are the 8 inferred relationships involving `LifecycleStatus` (e.g. with `Obligation` and `ObligationService`) actually correct?**
  _`LifecycleStatus` has 8 INFERRED edges - model-reasoned connections that need verification._
- **Are the 6 inferred relationships involving `OwnershipStatus` (e.g. with `Obligation` and `ObligationService`) actually correct?**
  _`OwnershipStatus` has 6 INFERRED edges - model-reasoned connections that need verification._