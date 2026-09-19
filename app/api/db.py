"""Database configuration and session management for MasCloner.

Supports both direct SQLAlchemy operations and Alembic migrations.
"""

from __future__ import annotations

import logging
import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, Generator

from sqlalchemy import create_engine, event, func, inspect, select, text, Engine
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from .models import Base, ConfigKV, FileEvent, Run

logger = logging.getLogger(__name__)

# Database configuration
DB_PATH = os.environ.get("MASCLONER_DB_PATH", "data/mascloner.db")

# Ensure database directory exists
db_path = Path(DB_PATH)
db_path.parent.mkdir(parents=True, exist_ok=True)

def configure_sqlite_pragmas(target_engine: Engine) -> None:
    """Apply durable SQLite PRAGMAs (WAL, synchronous=NORMAL, foreign_keys=ON, busy_timeout=5000)."""
    @event.listens_for(target_engine, "connect")
    def _set_pragmas(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys = ON")
        cursor.execute("PRAGMA journal_mode = WAL")
        cursor.execute("PRAGMA synchronous = NORMAL")
        cursor.execute("PRAGMA busy_timeout = 5000")
        cursor.close()


def create_sqlite_engine(database_path: str | Path) -> Engine:
    """Create and configure a SQLAlchemy Engine for SQLite with durable pragmas."""
    eng = create_engine(
        f"sqlite:///{database_path}",
        future=True,
        pool_pre_ping=True,
        echo=False,
        connect_args={"check_same_thread": False},
    )
    configure_sqlite_pragmas(eng)
    return eng


# Create engine with appropriate settings
engine = create_sqlite_engine(DB_PATH)

# Create session factory
SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    autocommit=False,
    future=True,
)


def init_db() -> None:
    """Initialize database by creating all tables.

    For new installations, this creates tables directly.
    For existing databases, tables are already present.
    Use Alembic for schema migrations after initial creation.
    """
    try:
        database_file = Path(DB_PATH)
        if database_file.is_file():
            probe = sqlite3.connect(database_file.resolve().as_uri() + "?mode=ro", uri=True)
            try:
                probe.execute("PRAGMA query_only=ON")
                table_names = {
                    row[0]
                    for row in probe.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
                }
            finally:
                probe.close()
        else:
            table_names = set()
        # A database which contains unrelated tables is an existing database,
        # not a fresh MasCloner installation.  It must pass classification
        # below instead of being silently mixed with a new schema.
        created_new_database = not table_names or table_names == {"sqlite_sequence"}
        if created_new_database:
            Base.metadata.create_all(bind=engine)
            logger.info("Database initialized successfully at %s", DB_PATH)

            # Metadata creation already produced the current schema.  This is
            # the sole safe direct-head stamp: there was no pre-existing data.
            from alembic.command import stamp
            stamp(_alembic_config(DB_PATH), "head")

        if not upgrade_database_to_head(Path(DB_PATH)):
            raise RuntimeError("Database schema upgrade failed; refusing to start with an unknown schema")

    except SQLAlchemyError as e:
        logger.error("Failed to initialize database: %s", e)
        raise


LEGACY_BASELINE_REVISION = "20241224_000001"


def classify_legacy_baseline(database_path: str | Path) -> str | None:
    """Return the safe Alembic baseline for an unstamped legacy database.

    Only the documented v2 schema is accepted.  A database with partial v3
    columns is deliberately rejected because stamping it would hide an
    interrupted upgrade and make data repair impossible to reason about.
    """
    candidate = Path(database_path)
    if not candidate.is_file():
        return None
    # Classification must remain read-only, including on an unknown database;
    # the normal application engine enables WAL and would mutate its header.
    probe = sqlite3.connect(candidate.resolve().as_uri() + "?mode=ro", uri=True)
    try:
        probe.execute("PRAGMA query_only=ON")
        tables = {row[0] for row in probe.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        if "alembic_version" in tables:
            return "stamped"
        required_tables = {"config", "runs", "file_events"}
        if not required_tables.issubset(tables):
            return None
        config_columns = {row[1] for row in probe.execute("PRAGMA table_info(config)")}
        run_columns = {row[1] for row in probe.execute("PRAGMA table_info(runs)")}
        required_config = {"key", "value", "updated_at"}
        required_runs = {
            "id", "started_at", "finished_at", "status", "num_added",
            "num_updated", "bytes_transferred", "errors", "log_path",
        }
        if not required_config.issubset(config_columns) or not required_runs.issubset(run_columns):
            return None
        if "provenance" in config_columns or "message" in run_columns:
            # Older releases sometimes created the complete ORM schema with
            # Base.metadata.create_all before Alembic was introduced.  It is
            # safe to stamp only an exact current schema with canonical run
            # values; a partial v3 schema remains unclassifiable.
            expected_config = {"key", "value", "updated_at", "provenance"}
            expected_runs = required_runs | {"message"}
            expected_events = {
                "id", "run_id", "timestamp", "action", "file_path",
                "file_size", "file_hash", "message",
            }
            event_columns = {row[1] for row in probe.execute("PRAGMA table_info(file_events)")}
            statuses = {
                str(row[0]).lower()
                for row in probe.execute("SELECT DISTINCT status FROM runs")
                if row[0]
            }
            canonical = {"pending", "running", "completed", "failed", "aborted", "skipped"}
            if (
                config_columns == expected_config
                and run_columns == expected_runs
                and event_columns == expected_events
                and statuses.issubset(canonical)
            ):
                return "head"
            return None
        run_indexes = {row[1] for row in probe.execute("PRAGMA index_list(runs)")}
        if "idx_runs_status" in run_indexes:
            return "20241226_000001"
        return LEGACY_BASELINE_REVISION
    finally:
        probe.close()


def _alembic_config(database_path: str | Path):
    from alembic.config import Config

    project_root = Path(__file__).parent.parent.parent
    alembic_cfg_path = project_root / "alembic.ini"
    if not alembic_cfg_path.exists():
        raise FileNotFoundError(f"alembic.ini not found at {alembic_cfg_path}")
    alembic_cfg = Config(str(alembic_cfg_path))
    alembic_cfg.set_main_option("script_location", str(project_root / "alembic"))
    alembic_cfg.set_main_option("sqlalchemy.url", f"sqlite:///{Path(database_path)}")
    return alembic_cfg


def upgrade_database_to_head(database_path: str | Path) -> bool:
    """Classify, baseline, and upgrade a database without unsafe head stamps."""
    try:
        from alembic.command import stamp, upgrade

        baseline = classify_legacy_baseline(database_path)
        if baseline is None:
            logger.error("Refusing Alembic upgrade for unrecognized database schema at %s", database_path)
            return False
        config = _alembic_config(database_path)
        if baseline != "stamped":
            logger.info("Stamping supported legacy schema at %s", baseline)
            stamp(config, baseline)
        upgrade(config, "head")
        if not _has_current_schema(database_path):
            logger.error("Alembic reported success but required v3 schema is missing at %s", database_path)
            return False
        logger.info("Database migrations completed successfully")
        return True
    except ImportError:
        logger.warning("Alembic not installed, cannot run migrations")
        return False
    except Exception as exc:
        logger.error("Database schema upgrade failed: %s", exc)
        return False


def _has_current_schema(database_path: str | Path) -> bool:
    """Verify the columns that make a head stamp meaningful for v3 data."""
    probe = create_engine(f"sqlite:///{Path(database_path)}", future=True)
    try:
        inspector = inspect(probe)
        tables = set(inspector.get_table_names())
        if not {"config", "runs", "file_events", "alembic_version"}.issubset(tables):
            return False
        config_columns = {item["name"] for item in inspector.get_columns("config")}
        run_columns = {item["name"] for item in inspector.get_columns("runs")}
        if "provenance" not in config_columns or "message" not in run_columns:
            return False
        canonical_statuses = {"pending", "running", "completed", "failed", "aborted", "skipped"}
        with probe.connect() as connection:
            statuses = {str(row[0]).lower() for row in connection.execute(text("SELECT DISTINCT status FROM runs")) if row[0]}
            revisions = [row[0] for row in connection.execute(text("SELECT version_num FROM alembic_version"))]
        if not statuses.issubset(canonical_statuses) or len(revisions) != 1:
            return False
        from alembic.script import ScriptDirectory
        return revisions[0] == ScriptDirectory.from_config(_alembic_config(database_path)).get_current_head()
    finally:
        probe.dispose()


def stamp_database_head() -> bool:
    """Stamp the database with the current Alembic head revision.

    This is useful for marking existing databases as up-to-date with migrations.

    Returns:
        True if successful, False otherwise.
    """
    try:
        # Kept for external callers, but intentionally no longer stamps an
        # arbitrary database to head.
        return upgrade_database_to_head(DB_PATH)

    except ImportError:
        logger.warning("Alembic not installed, cannot stamp database")
        return False
    except Exception as e:
        logger.error("Failed to stamp database: %s", e)
        return False


def run_migrations() -> bool:
    """Run all pending Alembic migrations.

    Returns:
        True if successful, False otherwise.
    """
    return upgrade_database_to_head(DB_PATH)


def get_db() -> Generator[Session, None, None]:
    """Dependency to get database session for FastAPI."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@contextmanager
def get_db_context() -> Generator[Session, None, None]:
    """Context manager for database sessions."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_db_session() -> Session:
    """Get a database session for direct use.

    Note: Caller is responsible for closing the session.
    Prefer using get_db_context() for automatic cleanup.
    """
    return SessionLocal()


def test_db_connection() -> bool:
    """Test database connectivity."""
    try:
        with get_db_context() as db:
            db.execute(text("SELECT 1"))
        logger.info("Database connection test successful")
        return True
    except Exception as e:
        logger.error("Database connection test failed: %s", e)
        return False


def backup_database(backup_path: str) -> bool:
    """Create a backup of the database.

    Args:
        backup_path: Path where the backup should be created.

    Returns:
        True if successful, False otherwise.
    """
    try:
        import shutil

        backup_path_obj = Path(backup_path)
        backup_path_obj.parent.mkdir(parents=True, exist_ok=True)

        shutil.copy2(DB_PATH, backup_path)
        logger.info("Database backup created: %s", backup_path)
        return True
    except Exception as e:
        logger.error("Database backup failed: %s", e)
        return False


def get_db_info() -> Dict[str, Any]:
    """Get database information and statistics.

    Returns:
        Dictionary with database path, size, table counts, and connection status.
    """
    try:
        with get_db_context() as db:
            runs_count = db.execute(select(func.count(Run.id))).scalar()
            events_count = db.execute(select(func.count(FileEvent.id))).scalar()
            config_count = db.execute(select(func.count(ConfigKV.key))).scalar()

            db_size = Path(DB_PATH).stat().st_size if Path(DB_PATH).exists() else 0

            # Get Alembic version if available
            alembic_version = None
            try:
                result = db.execute(text("SELECT version_num FROM alembic_version"))
                row = result.fetchone()
                if row:
                    alembic_version = row[0]
            except Exception:
                pass  # Table might not exist

            return {
                "database_path": DB_PATH,
                "database_size_bytes": db_size,
                "runs_count": runs_count,
                "events_count": events_count,
                "config_count": config_count,
                "alembic_version": alembic_version,
                "connection_ok": True,
            }
    except Exception as e:
        logger.error("Failed to get database info: %s", e)
        return {
            "database_path": DB_PATH,
            "connection_ok": False,
            "error": str(e),
        }
