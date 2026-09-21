# Clinical Completion Engine (CCE)

**Checkpoint 1.1: Foundational Database Schema, State Dimensions, and Defensive Audit Infrastructure**

The Clinical Completion Engine (CCE) is an auditable, safety-critical backend engine designed to eliminate the healthcare failure mode: **"ordered does not mean completed."** In hospital and ambulatory workflows, required actions (e.g. repeat renal panels post-AKI, 3-month imaging surveillance, or specialist referrals) are often documented but fail to be completed, completed past the safe window, or returned without clinician review.

---

## Key Principles & Design Decisions

### 1. Multi-Dimensional State Tracking
Single-status fields inevitably cause premature closure or ambiguous state. CCE separates status across four orthogonal, independently tracked dimensions:
- **`lifecycle_status`**: `DRAFT`, `CONFIRMED`, `ACTIVE`, `COMPLETE`, `CANCEL_REQUESTED`, `CANCELLED`, `SUPERSEDED`, `INVALID`
- **`timeliness_status`**: `NOT_DUE`, `DUE`, `OVERDUE`, `NOT_APPLICABLE`
- **`evidence_review_status`**: `NO_EVIDENCE`, `ACTION_EVIDENCE_RECEIVED`, `AWAITING_REVIEW_EVIDENCE`, `AMBIGUOUS_REVIEW_EVIDENCE`, `VERIFIED_COMPLETE`
- **`ownership_status`**: `OWNED`, `NO_OWNER`

### 2. Defensive Auditability & Sequence Invariants (`audit_seq`)
- **Explicit Creation Audit Log**: Obligations must be paired with an initial `CREATION` event (`audit_seq = 1`) capturing raw extraction provenance, actor, and payload.
- **Strict 1-to-1 Sequence Pairing**: Each mutation increments `audit_seq`. A PostgreSQL deferred constraint trigger (`AFTER INSERT OR UPDATE ON obligations DEFERRABLE INITIALLY DEFERRED`) ensures that no transaction can commit without inserting a matching `obligation_audit_log` row for that exact `audit_seq`.
- **Multi-Update Protection**: If an obligation undergoes multiple status transitions in a single transaction (e.g., owner assignment followed by timeliness update), both transitions must log their respective sequence entries. Neither masks the other.
- **Append-Only Immutability**: Database triggers forbid hard deletions on `obligations` and forbid both updates and deletions on `obligation_audit_log`.

### 3. Supersession vs. Cancellation
- **`SUPERSEDED`**: Applied when clinical care legitimately changes (e.g., medication switched from Warfarin to DOAC; or cross-border patient transfer). Enforced by database constraint `chk_obligation_superseded` requiring either a successor pointer (`superseded_by_id`) or an explicit `migration_flag`.
- **`CANCELLED`**: Administrative cancellation (e.g., erroneous NLP extraction).

### 4. NHS-Realistic Ownership Constraints
- When `ownership_status = 'OWNED'`, at least one of `assigned_team` or `assigned_user_id` is mandatory.
- When `ownership_status = 'NO_OWNER'`, `assigned_team` may remain populated (e.g., "Ward 4B Team") to preserve ward/service context while unallocated to an individual clinician.

---

## Directory Structure

```
medical_catalogue/
├── cce/
│   ├── __init__.py
│   ├── enums.py                  # PostgreSQL-mapped StrEnum definitions
│   ├── models.py                 # SQLAlchemy 2.0 Mapped & mapped_column models
│   ├── audit.py                  # Audit enforcement listeners and custom exceptions
│   ├── service.py                # Transaction-safe domain service operations
│   └── ddl/
│       ├── schema.sql            # Raw PostgreSQL DDL: types, tables, constraints, indexes
│       └── triggers.sql          # PL/pgSQL triggers: anti-delete, audit_seq, deferred audit
├── migrations/                   # Alembic database migrations
│   ├── env.py
│   ├── script.py.mako
│   └── versions/
│       └── 0001_initial_cce_schema.py
├── tests/                        # PostgreSQL automated test suite
│   ├── conftest.py               # Fixtures managing DB lifecycle and session teardown
│   ├── test_raw_sql.py           # Raw DDL validation against PostgreSQL
│   ├── test_models.py            # ORM dimensions, constraints, and relationships
│   ├── test_audit_enforcement.py # Audit enforcement, multi-update seq, anti-delete
│   └── test_supersession.py      # Supersession semantics vs cancellation
├── docker-compose.yml            # PostgreSQL 16 Alpine service
├── alembic.ini
└── pyproject.toml
```

---

## Running the Verification Suite

Ensure the local PostgreSQL 16 container is running:
```bash
docker compose up -d
```

Run all tests via `pytest`:
```bash
.venv/bin/pytest -v
```

---

## Code Guidelines & CI/CD Pipeline

The project enforces strict code quality, type safety, and test coverage standards:

### 1. CI/CD GitHub Actions (`.github/workflows/ci.yml`)
Runs automatically on all pushes and pull requests across Python 3.11, 3.12, and 3.13:
- **Linting & Formatting**: Ruff checks for PEP 8, import sorting (`isort`), modern Python idioms (`pyupgrade`), and code bug hazards (`flake8-bugbear`).
- **Static Type Checking**: Mypy verifies type safety across all `Mapped[...]` and SQLAlchemy models.
- **Alembic Migration Verification**: Tests forward upgrade (`alembic upgrade head`) and rollback (`alembic downgrade base`) on a real PostgreSQL 16 service container.
- **Automated Testing & Coverage**: Runs pytest suite with 85%+ coverage enforcement (`--cov=cce`).

### 2. Local Developer Quality Script
Run all checks (linting, formatting, type checking, and tests) with a single command:
```bash
./scripts/check.sh
```

Or individual tools:
```bash
.venv/bin/ruff check .
.venv/bin/ruff format --check .
.venv/bin/mypy
.venv/bin/pytest --cov=cce --cov-report=term-missing
```

Pre-commit hooks are also configured via `.pre-commit-config.yaml`.

---

## Automated Semantic Release

The repository uses [python-semantic-release](https://python-semantic-release.readthedocs.io/) to automate semantic versioning, changelog generation, and GitHub Releases based on [Conventional Commits](https://www.conventionalcommits.org/):

| Commit Type | Release Type | Example |
|---|---|---|
| `fix:` | Patch Release (`0.1.0` $\rightarrow$ `0.1.1`) | `fix(audit): correct deferred trigger timestamp check` |
| `feat:` | Minor Release (`0.1.0` $\rightarrow$ `0.2.0`) | `feat(models): add ambiguous review item priority` |
| `feat!:` or `BREAKING CHANGE:` | Major Release (`0.1.0` $\rightarrow$ `1.0.0`) | `feat!: overhaul state machine transitions` |
| `chore:`, `docs:`, `ci:` | No Release | `docs: update deployment guidelines` |

### Release Workflow
When code is merged to `main` and passes all CI quality gates (linting, typing, migrations, tests):
1. Analyzes commits since the last release.
2. Calculates the next semantic version number.
3. Automatically updates `version` in `pyproject.toml` and `__version__` in `cce/__init__.py`.
4. Appends release notes to `CHANGELOG.md`.
5. Commits changes with `chore(release): vX.Y.Z [skip ci]`, creates git tag `vX.Y.Z`, and creates a GitHub Release.

