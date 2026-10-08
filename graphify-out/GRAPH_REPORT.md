# Graph Report - medical_catalogue  (2026-10-08)

## Corpus Check
- 28 files · ~13,387 words
- Verdict: corpus is large enough that graph structure adds value.
- Unclassified: 3 file(s) not represented in the graph (top: (none) 1, .ini 1, .mako 1)

## Summary
- 288 nodes · 939 edges · 22 communities (14 shown, 8 thin omitted)
- Extraction: 76% EXTRACTED · 24% INFERRED · 0% AMBIGUOUS · INFERRED: 226 edges (avg confidence: 0.95)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `5a303537`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- ObligationAuditLog
- ObligationService
- Clinical Completion Engine
- conftest.py
- Obligation
- AuditEventType
- build_audit_log
- LifecycleStatus
- .update_dimensions
- cce/__init__.py
- .process_event
- env.py
- Graphify Repository Workflow
- .get_dimensions_snapshot
- check.sh
- medical_catalogue_cce
- CHANGELOG
- test_multiple_updates_in_single_transaction_require_individual_audits
- test_prohibit_hard_deletion_on_obligations_raw_sql
- test_prohibit_mutation_or_deletion_on_audit_log_raw_sql
- test_insert_obligation_without_audit_log_fails_in_raw_sql
- test_update_obligation_without_audit_log_fails_in_raw_sql

## God Nodes (most connected - your core abstractions)
1. `LifecycleStatus` - 54 edges
2. `EvidenceReviewStatus` - 48 edges
3. `transition()` - 47 edges
4. `OwnershipStatus` - 47 edges
5. `TimelinessStatus` - 46 edges
6. `ObligationService` - 44 edges
7. `ObligationStateTuple` - 38 edges
8. `AuditEventType` - 37 edges
9. `Obligation` - 36 edges
10. `_make_context()` - 25 edges

## Surprising Connections (you probably didn't know these)
- `NHS-Realistic Ownership Constraints` --references--> `Obligation`  [EXTRACTED]
  README.md → cce/models.py
- `Supersession vs Cancellation` --references--> `Domain Service Operations`  [INFERRED]
  README.md → cce/service.py
- `test_insert_obligation_without_audit_log_fails_in_orm()` --uses--> `AuditMissingError`  [INFERRED]
  tests/test_audit_enforcement.py → cce/audit.py
- `test_update_obligation_without_audit_log_fails_in_orm()` --uses--> `AuditMissingError`  [INFERRED]
  tests/test_audit_enforcement.py → cce/audit.py
- `test_action_code_mismatch_raises_error_and_preserves_state()` --uses--> `InvalidStateTransitionError`  [INFERRED]
  tests/test_state_machine_service.py → cce/audit.py

## Import Cycles
- None detected.

## Communities (22 total, 8 thin omitted)

### Community 0 - "ObligationAuditLog"
Cohesion: 0.33
Nodes (6): Base, ObligationAuditLog, Append-only, immutable clinical audit ledger for obligations., DeclarativeBase, Validate that OWNED without assigned_team or assigned_user_id violates…, test_invalid_ownership_raises_integrity_error()

### Community 1 - "ObligationService"
Cohesion: 0.13
Nodes (22): ImmutabilityViolationError, Raised when an operation attempts to mutate or delete immutable clinical…, ObligationService, datetime, Safe, auditable transactional service operations for Clinical Obligations., Create and ingest a new clinical obligation with its mandatory CREATION audit…, Verify direct hard DELETE on obligations is strictly blocked in ORM…, Verify obligation_audit_log deletion is blocked in ORM before_flush. (+14 more)

### Community 2 - "Clinical Completion Engine"
Cohesion: 0.13
Nodes (15): Audit Enforcement, Domain Service Operations, CCE PostgreSQL Service, CI/CD Pipeline, Lint and Typecheck Job, Semantic Release, Test and Migrations Job, Pre-commit Hooks (+7 more)

### Community 3 - "conftest.py"
Cohesion: 0.08
Nodes (26): AuditMissingError, AuditViolationError, Base exception for audit and governance violations., Raised when an obligation mutation lacks a corresponding audit log entry., Register SQLAlchemy Session-level event listeners to enforce defensive audit…, register_audit_listeners(), _enforce_audit_invariants_before_flush(), collections_abc (+18 more)

### Community 4 - "Obligation"
Cohesion: 0.24
Nodes (9): Obligation, Primary clinical obligation entity. Tracks four independent state dimensions…, Transition an obligation to SUPERSEDED and link it to replacement or migration…, Verify ORM before_flush rejects inserting an Obligation without a creation…, test_insert_obligation_without_audit_log_fails_in_orm(), Verify superseding an obligation by linking to a replacement obligation., Verify superseding an obligation using a structured migration flag (e.g.…, test_supersede_with_migration_flag() (+1 more)

### Community 5 - "AuditEventType"
Cohesion: 0.26
Nodes (14): AmbiguousItemStatus, AuditEventType, Class of audit event logged in immutable obligation audit ledger., Status of an ambiguous evidence review queue item., AmbiguousReviewItem, Review queue entity for ambiguous evidence matching requiring clinical…, datetime, enum (+6 more)

### Community 6 - "build_audit_log"
Cohesion: 0.40
Nodes (5): build_audit_log(), Any, Build an ObligationAuditLog entry paired to an obligation's current or target…, Verify build_audit_log helper produces a valid ObligationAuditLog instance., test_build_audit_log_helper()

### Community 7 - "LifecycleStatus"
Cohesion: 0.18
Nodes (49): InvalidStateTransitionError, Raised when an illegal state machine transition is attempted., ObligationStateTuple, DomainEvent, Execute a pure, side-effect-free transition on an obligation state. Enforces…, Immutable 4-dimensional status tuple representing an obligation's exact state., Convenience constructor accepting either enum instances or string names., Convert state tuple to a string-keyed dictionary matching audit snapshot format. (+41 more)

### Community 8 - ".update_dimensions"
Cohesion: 0.15
Nodes (11): Any, Session, Atomically update state dimensions and record a corresponding audit log., Administratively cancel an obligation with clinical rationale., Assign or update accountable clinical owner., Verify ObligationService.update_dimensions updates fields and logs an audit…, Verify ObligationService.assign_owner allocates clinician ownership and creates…, test_assign_owner_service() (+3 more)

### Community 9 - "cce/__init__.py"
Cohesion: 0.06
Nodes (54): BaseModel, cce_engine, State machine engine package for Clinical Completion Engine (CCE)., Pure, deterministic state machine transition engine for Clinical Completion…, Deterministic result of processing a DomainEvent against an…, Indicate whether state dimensions or updated fields changed., Immutable domain context supplied to pure transition evaluations., TransitionContext (+46 more)

### Community 10 - ".process_event"
Cohesion: 0.13
Nodes (12): Extract a TransitionContext snapshot from an active Obligation entity., Construct an ObligationStateTuple from a SQLAlchemy Obligation instance., DomainEvent, Process a domain event against an obligation using the pure transition engine.…, Test that ManualOverrideEvent transitions obligation to COMPLETE despite…, Test SupersedePlanEvent and CancelObligationEvent via ObligationService., Test AssignOwnershipEvent via ObligationService., Test that a guard failure in process_event leaves obligation state untouched. (+4 more)

### Community 11 - "env.py"
Cohesion: 0.24
Nodes (6): alembic, logging_config, get_url(), run_migrations_offline(), run_migrations_online(), sqlalchemy_dialects

### Community 12 - "Graphify Repository Workflow"
Cohesion: 0.67
Nodes (3): Graphify Knowledge Graph Rule, Graphify Pipeline Workflow, Graphify Repository Workflow

### Community 16 - "CHANGELOG"
Cohesion: 0.50
Nodes (3): CHANGELOG, Features, v0.1.0 (2026-09-21)

## Knowledge Gaps
- **10 isolated node(s):** `medical_catalogue_cce`, `check.sh script`, `Features`, `Graphify Knowledge Graph Rule`, `Graphify Pipeline Workflow` (+5 more)
  These have ≤1 connection - possible missing edges or undocumented components. (Counts symbols only; 116 node(s) total have ≤1 connection when file, concept and rationale nodes are included.)
- **8 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `Obligation` connect `Obligation` to `ObligationAuditLog`, `ObligationService`, `Clinical Completion Engine`, `conftest.py`, `AuditEventType`, `build_audit_log`, `LifecycleStatus`, `.update_dimensions`, `cce/__init__.py`, `.process_event`, `.get_dimensions_snapshot`?**
  _High betweenness centrality (0.175) - this node is a cross-community bridge._
- **Why does `NHS-Realistic Ownership Constraints` connect `Clinical Completion Engine` to `Obligation`?**
  _High betweenness centrality (0.090) - this node is a cross-community bridge._
- **Are the 39 inferred relationships involving `LifecycleStatus` (e.g. with `ObligationStateTuple` and `transition()`) actually correct?**
  _`LifecycleStatus` has 39 INFERRED edges - model-reasoned connections that need verification._
- **Are the 34 inferred relationships involving `EvidenceReviewStatus` (e.g. with `ObligationStateTuple` and `transition()`) actually correct?**
  _`EvidenceReviewStatus` has 34 INFERRED edges - model-reasoned connections that need verification._
- **Are the 14 inferred relationships involving `transition()` (e.g. with `AuditEventType` and `EvidenceReviewStatus`) actually correct?**
  _`transition()` has 14 INFERRED edges - model-reasoned connections that need verification._
- **Are the 32 inferred relationships involving `OwnershipStatus` (e.g. with `ObligationStateTuple` and `transition()`) actually correct?**
  _`OwnershipStatus` has 32 INFERRED edges - model-reasoned connections that need verification._
- **Are the 32 inferred relationships involving `TimelinessStatus` (e.g. with `ObligationStateTuple` and `transition()`) actually correct?**
  _`TimelinessStatus` has 32 INFERRED edges - model-reasoned connections that need verification._