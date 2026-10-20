# Graph Report - medical_catalogue  (2026-10-20)

## Corpus Check
- 33 files · ~17,758 words
- Verdict: corpus is large enough that graph structure adds value.
- Unclassified: 4 file(s) not represented in the graph (top: (none) 1, .csv 1, .ini 1)

## Summary
- 381 nodes · 1238 edges · 24 communities (22 shown, 2 thin omitted)
- Extraction: 76% EXTRACTED · 24% INFERRED · 0% AMBIGUOUS · INFERRED: 297 edges (avg confidence: 0.95)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `3359de9b`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- run_case_simulation.py
- audit.py
- Clinical Completion Engine
- ScenarioRunner
- Obligation
- state_machine.py
- ObligationService
- LifecycleStatus
- ObligationAuditLog
- test_domain_events.py
- test_state_machine_service.py
- env.py
- Graphify Repository Workflow
- parser.py
- check.sh
- medical_catalogue_cce
- CHANGELOG
- runner.py
- events.py
- SyntheticScenario
- cce/__init__.py
- ScenarioRunResult
- SupersedePlanEvent
- db_session

## God Nodes (most connected - your core abstractions)
1. `LifecycleStatus` - 68 edges
2. `TimelinessStatus` - 61 edges
3. `EvidenceReviewStatus` - 61 edges
4. `OwnershipStatus` - 57 edges
5. `transition()` - 48 edges
6. `ObligationService` - 46 edges
7. `Obligation` - 45 edges
8. `ObligationStateTuple` - 42 edges
9. `AuditEventType` - 40 edges
10. `ScenarioRunner` - 33 edges

## Surprising Connections (you probably didn't know these)
- `NHS-Realistic Ownership Constraints` --references--> `Obligation`  [EXTRACTED]
  README.md → cce/models.py
- `Supersession vs Cancellation` --references--> `Domain Service Operations`  [INFERRED]
  README.md → cce/service.py
- `test_action_code_mismatch_raises_error_and_preserves_state()` --uses--> `InvalidStateTransitionError`  [INFERRED]
  tests/test_state_machine_service.py → cce/audit.py
- `test_update_obligation_without_audit_log_fails_in_orm()` --uses--> `LifecycleStatus`  [INFERRED]
  tests/test_audit_enforcement.py → cce/enums.py
- `test_insert_complete_obligation_with_four_dimensions()` --uses--> `LifecycleStatus`  [INFERRED]
  tests/test_models.py → cce/enums.py

## Import Cycles
- None detected.

## Communities (24 total, 2 thin omitted)

### Community 0 - "run_case_simulation.py"
Cohesion: 0.13
Nodes (19): argparse, Register SQLAlchemy Session-level event listeners to enforce defensive audit…, register_audit_listeners(), rich, rich_console, rich_panel, rich_table, rich_text (+11 more)

### Community 1 - "audit.py"
Cohesion: 0.09
Nodes (28): AuditMissingError, AuditViolationError, ImmutabilityViolationError, Base exception for audit and governance violations., Raised when an obligation mutation lacks a corresponding audit log entry., Raised when an operation attempts to mutate or delete immutable clinical…, _enforce_audit_invariants_before_flush(), Exception (+20 more)

### Community 2 - "Clinical Completion Engine"
Cohesion: 0.13
Nodes (15): Audit Enforcement, Domain Service Operations, CCE PostgreSQL Service, CI/CD Pipeline, Lint and Typecheck Job, Semantic Release, Test and Migrations Job, Pre-commit Hooks (+7 more)

### Community 3 - "ScenarioRunner"
Cohesion: 0.09
Nodes (27): Simulation runner and time machine for CCE synthetic clinical obligations., ScenarioRunner, parametrize, pathlib, pytest, sqlalchemy, Verify compound dimension index and partial active-risk index exist., Verify all 6 PostgreSQL native enum types exist and contain expected values. (+19 more)

### Community 4 - "Obligation"
Cohesion: 0.20
Nodes (9): Extract a TransitionContext snapshot from an active Obligation entity., Obligation, Return a snapshot dict of the 4 independent status dimensions., Primary clinical obligation entity. Tracks four independent state dimensions…, datetime, Verify superseding an obligation by linking to a replacement obligation., Verify superseding an obligation using a structured migration flag (e.g.…, test_supersede_with_migration_flag() (+1 more)

### Community 5 - "state_machine.py"
Cohesion: 0.20
Nodes (16): Pure, deterministic state machine transition engine for Clinical Completion…, AmbiguousItemStatus, Status of an ambiguous evidence review queue item., AmbiguousReviewItem, Base, Review queue entity for ambiguous evidence matching requiring clinical…, datetime, DeclarativeBase (+8 more)

### Community 6 - "ObligationService"
Cohesion: 0.19
Nodes (16): build_audit_log(), Any, Build an ObligationAuditLog entry paired to an obligation's current or target…, AuditEventType, Class of audit event logged in immutable obligation audit ledger., ObligationService, Atomically update state dimensions and record a corresponding audit log., Safe, auditable transactional service operations for Clinical Obligations. (+8 more)

### Community 7 - "LifecycleStatus"
Cohesion: 0.14
Nodes (57): InvalidStateTransitionError, Raised when an illegal state machine transition is attempted., ObligationStateTuple, DomainEvent, Execute a pure, side-effect-free transition on an obligation state. Enforces…, Immutable 4-dimensional status tuple representing an obligation's exact state., Convenience constructor accepting either enum instances or string names., Convert state tuple to a string-keyed dictionary matching audit snapshot format. (+49 more)

### Community 8 - "ObligationAuditLog"
Cohesion: 0.21
Nodes (9): ObligationAuditLog, Append-only, immutable clinical audit ledger for obligations., Any, Session, Transition an obligation to SUPERSEDED and link it to replacement or migration…, Administratively cancel an obligation with clinical rationale., Assign or update accountable clinical owner., Verify administrative cancellation is kept distinct from clinical supersession. (+1 more)

### Community 9 - "test_domain_events.py"
Cohesion: 0.19
Nodes (14): CancelObligationEvent, HumanConfirmEvent, ManualOverrideEvent, Administrative or clinical cancellation; requires structured reason_code and…, Clinician forces COMPLETE despite missing verification. Requires mandatory…, Confirms a DRAFT obligation, transitioning it to ACTIVE., Unit tests for strongly typed domain events (Pydantic V2)., test_base_event_mandatory_fields() (+6 more)

### Community 10 - "test_state_machine_service.py"
Cohesion: 0.14
Nodes (18): DomainEvent, Process a domain event against an obligation using the pure transition engine.…, Create and ingest a new clinical obligation with its mandatory CREATION audit…, Validate NHS clinical reality: NO_OWNER can retain assigned_team context (e.g.…, test_relaxed_ownership_constraint_in_models(), Integration tests for state machine execution coordinated via ObligationService…, Test that AmbiguousEvidenceFlaggedEvent creates an AmbiguousReviewItem in DB., Test that ManualOverrideEvent transitions obligation to COMPLETE despite… (+10 more)

### Community 11 - "env.py"
Cohesion: 0.22
Nodes (7): alembic, logging_config, get_url(), run_migrations_offline(), run_migrations_online(), os, sqlalchemy_dialects

### Community 12 - "Graphify Repository Workflow"
Cohesion: 0.67
Nodes (3): Graphify Knowledge Graph Rule, Graphify Pipeline Workflow, Graphify Repository Workflow

### Community 13 - "parser.py"
Cohesion: 0.12
Nodes (17): AmbiguousEvidenceFlaggedEvent, ClinicalReviewDocumentedEvent, DiagnosticReportReceivedEvent, Ingested evidence cannot be deterministically matched with high confidence., A lab test or imaging report has landed (e.g., blood test processed). Must…, A clinician has documented their review of the diagnostic report. Must contain…, DomainEvent, UUID (+9 more)

### Community 16 - "CHANGELOG"
Cohesion: 0.50
Nodes (3): CHANGELOG, Features, v0.1.0 (2026-09-21)

### Community 17 - "runner.py"
Cohesion: 0.16
Nodes (15): Synthetic Event Simulator / Time Machine & Scenario Runner for CCE., calculate_headline(), calculate_should_flag(), Parser that converts SYNTHETIC CASES V1.csv into executable simulation…, Parse pipe-separated events timeline into a list of TimelineEvents., Calculate the clinical headline summary badge for an obligation. Reflects the…, Determine whether the obligation currently represents an active clinical safety…, Chronological event extracted from a scenario's events timeline. (+7 more)

### Community 18 - "events.py"
Cohesion: 0.20
Nodes (11): BaseModel, BaseDomainEvent, ClockTickEvent, datetime, Strongly typed domain events for the Clinical Completion Engine (CCE). All…, Abstract base model for all CCE domain events. Guarantees immutable event…, Evaluates current simulated time against due_window_start and due_window_end., _utc_now() (+3 more)

### Community 19 - "SyntheticScenario"
Cohesion: 0.15
Nodes (10): datetime, Path, Strongly-typed synthetic scenario loaded from SYNTHETIC CASES V1.csv., Check whether the scenario explicitly models draft confirmation., Map a relative day offset to an absolute UTC datetime., Read and parse all benchmark scenarios from a CSV file., SyntheticScenario, datetime (+2 more)

### Community 20 - "cce/__init__.py"
Cohesion: 0.22
Nodes (8): cce_engine, State machine engine package for Clinical Completion Engine (CCE)., Deterministic result of processing a DomainEvent against an…, Indicate whether state dimensions or updated fields changed., Immutable domain context supplied to pure transition evaluations., TransitionContext, TransitionResult, Clinical Completion Engine (CCE) - Safety-Critical Medical State Machine &…

### Community 21 - "ScenarioRunResult"
Cohesion: 0.22
Nodes (6): Construct an ObligationStateTuple from a SQLAlchemy Obligation instance., Execute a full scenario simulation from start to completion and verify results., Execute all loaded scenarios and return a mapping of case_id ->…, Comprehensive execution report for a synthetic benchmark scenario run., Initialize and persist the initial Obligation for a scenario in DRAFT or ACTIVE., ScenarioRunResult

### Community 22 - "SupersedePlanEvent"
Cohesion: 0.20
Nodes (7): AssignOwnershipEvent, Clinical plan changed legitimately; replaces obligation with superseded_by_id…, Assigns assigned_team and/or assigned_user_id., SupersedePlanEvent, model_validator, test_assign_ownership_event(), test_supersede_plan_event_validation()

### Community 23 - "db_session"
Cohesion: 0.25
Nodes (8): fixture, db_session(), engine(), Session, Session-wide PostgreSQL SQLAlchemy engine., Function-scoped SQLAlchemy Session with automatic teardown., Raw DBAPI connection for verifying direct SQL triggers and invariants., raw_conn()

## Knowledge Gaps
- **10 isolated node(s):** `medical_catalogue_cce`, `check.sh script`, `Features`, `Graphify Knowledge Graph Rule`, `Graphify Pipeline Workflow` (+5 more)
  These have ≤1 connection - possible missing edges or undocumented components. (Counts symbols only; 165 node(s) total have ≤1 connection when file, concept and rationale nodes are included.)
- **2 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `Obligation` connect `Obligation` to `run_case_simulation.py`, `audit.py`, `Clinical Completion Engine`, `ScenarioRunner`, `state_machine.py`, `ObligationService`, `LifecycleStatus`, `ObligationAuditLog`, `test_state_machine_service.py`, `parser.py`, `runner.py`, `cce/__init__.py`, `ScenarioRunResult`?**
  _High betweenness centrality (0.158) - this node is a cross-community bridge._
- **Why does `LifecycleStatus` connect `LifecycleStatus` to `audit.py`, `ScenarioRunner`, `Obligation`, `state_machine.py`, `ObligationService`, `ObligationAuditLog`, `test_state_machine_service.py`, `parser.py`, `runner.py`, `SyntheticScenario`, `cce/__init__.py`?**
  _High betweenness centrality (0.081) - this node is a cross-community bridge._
- **Why does `ScenarioRunner` connect `ScenarioRunner` to `run_case_simulation.py`, `Obligation`, `state_machine.py`, `ObligationService`, `LifecycleStatus`, `ObligationAuditLog`, `runner.py`, `events.py`, `SyntheticScenario`, `ScenarioRunResult`?**
  _High betweenness centrality (0.077) - this node is a cross-community bridge._
- **Are the 49 inferred relationships involving `LifecycleStatus` (e.g. with `ObligationStateTuple` and `transition()`) actually correct?**
  _`LifecycleStatus` has 49 INFERRED edges - model-reasoned connections that need verification._
- **Are the 43 inferred relationships involving `TimelinessStatus` (e.g. with `ObligationStateTuple` and `transition()`) actually correct?**
  _`TimelinessStatus` has 43 INFERRED edges - model-reasoned connections that need verification._
- **Are the 43 inferred relationships involving `EvidenceReviewStatus` (e.g. with `ObligationStateTuple` and `transition()`) actually correct?**
  _`EvidenceReviewStatus` has 43 INFERRED edges - model-reasoned connections that need verification._
- **Are the 38 inferred relationships involving `OwnershipStatus` (e.g. with `ObligationStateTuple` and `transition()`) actually correct?**
  _`OwnershipStatus` has 38 INFERRED edges - model-reasoned connections that need verification._