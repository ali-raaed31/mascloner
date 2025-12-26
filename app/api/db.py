"""Database configuration and session management for MasCloner.

Supports both direct SQLAlchemy operations and Alembic migrations.
"""

from __future__ import annotations

import logging
import os
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, Generator

from sqlalchemy import create_engine, func, select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from .models import Base, ConfigKV, FileEvent, Run

logger = logging.getLogger(__name__)

# Database configuration
DB_PATH = os.environ.get("MASCLONER_DB_PATH", "data/mascloner.db")

# Ensure database directory exists
db_path = Path(DB_PATH)
db_path.parent.mkdir(parents=True, exist_ok=True)

# Create engine with appropriate settings
engine = create_engine(
    f"sqlite:///{DB_PATH}",
    future=True,
    pool_pre_ping=True,
    echo=False,  # Set to True for SQL debugging
    connect_args={"check_same_thread": False},  # Required for SQLite with FastAPI
)

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
        Base.metadata.create_all(bind=engine)
        logger.info("Database initialized successfully at %s", DB_PATH)

        # Stamp the database with current Alembic head if alembic_version table is missing
        _stamp_alembic_if_needed()

    except SQLAlchemyError as e:
        logger.error("Failed to initialize database: %s", e)
        raise


def _stamp_alembic_if_needed() -> None:
    """Stamp existing database with Alembic version if not already stamped."""
    try:
        from sqlalchemy import inspect

        inspector = inspect(engine)
        if "alembic_version" not in inspector.get_table_names():
            # Database exists but hasn't been stamped - stamp with current head
            logger.info("Database not stamped with Alembic version, stamping...")
            stamp_database_head()
    except ImportError:
        # Alembic not installed, skip
        logger.debug("Alembic not available, skipping version stamp")
    except Exception as e:
        logger.warning("Failed to check/stamp Alembic version: %s", e)


def stamp_database_head() -> bool:
    """Stamp the database with the current Alembic head revision.

    This is useful for marking existing databases as up-to-date with migrations.

    Returns:
        True if successful, False otherwise.
    """
    try:
        from alembic import command
        from alembic.config import Config

        # Find alembic.ini relative to this file's location
        project_root = Path(__file__).parent.parent.parent
        alembic_cfg_path = project_root / "alembic.ini"

        if not alembic_cfg_path.exists():
            logger.warning("alembic.ini not found at %s", alembic_cfg_path)
            return False

        alembic_cfg = Config(str(alembic_cfg_path))
        alembic_cfg.set_main_option("script_location", str(project_root / "alembic"))

        command.stamp(alembic_cfg, "head")
        logger.info("Database stamped with Alembic head revision")
        return True

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
    try:
        from alembic import command
        from alembic.config import Config

        project_root = Path(__file__).parent.parent.parent
        alembic_cfg_path = project_root / "alembic.ini"

        if not alembic_cfg_path.exists():
            logger.warning("alembic.ini not found at %s", alembic_cfg_path)
            return False

        alembic_cfg = Config(str(alembic_cfg_path))
        alembic_cfg.set_main_option("script_location", str(project_root / "alembic"))

        command.upgrade(alembic_cfg, "head")
        logger.info("Database migrations completed successfully")
        return True

    except ImportError:
        logger.warning("Alembic not installed, cannot run migrations")
        return False
    except Exception as e:
        logger.error("Failed to run migrations: %s", e)
        return False


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
