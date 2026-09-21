import os
from pathlib import Path
from typing import Generator

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from cce.audit import register_audit_listeners
from cce.models import Base

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+psycopg://cce_user:cce_password@localhost:5432/cce_db"
)

PROJECT_ROOT = Path(__file__).parent.parent
SCHEMA_SQL_PATH = PROJECT_ROOT / "cce" / "ddl" / "schema.sql"
TRIGGERS_SQL_PATH = PROJECT_ROOT / "cce" / "ddl" / "triggers.sql"


@pytest.fixture(scope="session")
def engine():
    """Session-wide PostgreSQL SQLAlchemy engine."""
    eng = create_engine(DATABASE_URL, echo=False, pool_pre_ping=True)
    
    # Apply Schema and Triggers
    with eng.connect() as conn:
        with open(SCHEMA_SQL_PATH, "r", encoding="utf-8") as f:
            schema_sql = f.read()
            conn.execute(text(schema_sql))

        with open(TRIGGERS_SQL_PATH, "r", encoding="utf-8") as f:
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
    connection = engine.connect()
    transaction = connection.begin()
    session_factory = sessionmaker(bind=connection, expire_on_commit=False)
    session = session_factory()

    yield session

    session.close()
    if transaction.is_active:
        transaction.rollback()
    connection.close()

    # Clean tables between test runs using TRUNCATE
    with engine.connect() as conn:
        conn.execute(
            text("TRUNCATE TABLE ambiguous_review_items, obligation_audit_log, obligations RESTART IDENTITY CASCADE;")
        )
        conn.commit()


@pytest.fixture(scope="function")
def raw_conn(engine):
    """Raw DBAPI connection for verifying direct SQL triggers and invariants."""
    connection = engine.raw_connection()
    yield connection
    connection.close()

