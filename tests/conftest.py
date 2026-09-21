import os
from collections.abc import Generator
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from cce.audit import register_audit_listeners

DATABASE_URL = os.getenv(
    "DATABASE_URL", "postgresql+psycopg://cce_user:cce_password@localhost:5432/cce_db"
)

PROJECT_ROOT = Path(__file__).parent.parent
SCHEMA_SQL_PATH = PROJECT_ROOT / "cce" / "ddl" / "schema.sql"
TRIGGERS_SQL_PATH = PROJECT_ROOT / "cce" / "ddl" / "triggers.sql"


@pytest.fixture(scope="session")
def engine():
    """Session-wide PostgreSQL SQLAlchemy engine."""
    eng = create_engine(
        DATABASE_URL,
        echo=False,
        pool_pre_ping=True,
        connect_args={"options": "-c statement_timeout=5000"},
    )

    # Apply Schema and Triggers
    with eng.connect() as conn:
        with open(SCHEMA_SQL_PATH, encoding="utf-8") as f:
            schema_sql = f.read()
            conn.execute(text(schema_sql))

        with open(TRIGGERS_SQL_PATH, encoding="utf-8") as f:
            triggers_sql = f.read()
            conn.execute(text(triggers_sql))

        conn.commit()

    # Register ORM audit enforcement listeners
    register_audit_listeners()

    yield eng
    eng.dispose()


@pytest.fixture(scope="function")
def db_session(engine) -> Generator[Session, None, None]:
    """Function-scoped SQLAlchemy Session with automatic teardown."""
    with Session(engine, expire_on_commit=False) as session:
        yield session
        session.rollback()

    with engine.connect() as conn:
        conn.execute(
            text(
                "TRUNCATE TABLE ambiguous_review_items, obligation_audit_log, obligations RESTART IDENTITY CASCADE;"
            )
        )
        conn.commit()


@pytest.fixture(scope="function")
def raw_conn(engine):
    """Raw DBAPI connection for verifying direct SQL triggers and invariants."""
    connection = engine.raw_connection()
    yield connection
    connection.rollback()
    connection.close()

    with engine.connect() as conn:
        conn.execute(
            text(
                "TRUNCATE TABLE ambiguous_review_items, obligation_audit_log, obligations RESTART IDENTITY CASCADE;"
            )
        )
        conn.commit()
