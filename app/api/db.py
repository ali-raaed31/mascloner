"""Database configuration and session management for MasCloner."""

import os
import logging
from pathlib import Path
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.exc import SQLAlchemyError
from .models import Base

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
    connect_args={"check_same_thread": False}  # Required for SQLite with FastAPI
)

# Create session factory
SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    autocommit=False,
    future=True
)


def init_db() -> None:
    """Initialize database by creating all tables."""
    try:
        Base.metadata.create_all(bind=engine)
        logger.info(f"Database initialized successfully at {DB_PATH}")
    except SQLAlchemyError as e:
        logger.error(f"Failed to initialize database: {e}")
        raise


def get_db() -> Session:
    """Dependency to get database session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_db_session() -> Session:
    """Get a database session for direct use."""
    return SessionLocal()


def test_db_connection() -> bool:
    """Test database connectivity."""
    try:
        from sqlalchemy import text
        with get_db_session() as db:
            db.execute(text("SELECT 1"))
        logger.info("Database connection test successful")
        return True
    except Exception as e:
        logger.error(f"Database connection test failed: {e}")
        return False


# Database utilities
def backup_database(backup_path: str) -> bool:
    """Create a backup of the database."""
    try:
        import shutil
        
        backup_path_obj = Path(backup_path)
        backup_path_obj.parent.mkdir(parents=True, exist_ok=True)
        
        shutil.copy2(DB_PATH, backup_path)
        logger.info(f"Database backup created: {backup_path}")
        return True
    except Exception as e:
        logger.error(f"Database backup failed: {e}")
        return False


def get_db_info() -> dict:
    """Get database information and statistics."""
    try:
        with get_db_session() as db:
            from .models import Run, FileEvent, ConfigKV
            from sqlalchemy import func, select
            
            # Get table counts
            runs_count = db.execute(select(func.count(Run.id))).scalar()
            events_count = db.execute(select(func.count(FileEvent.id))).scalar()
            config_count = db.execute(select(func.count(ConfigKV.key))).scalar()
            
            # Get database file size
            db_size = Path(DB_PATH).stat().st_size if Path(DB_PATH).exists() else 0
            
            return {
                "database_path": DB_PATH,
                "database_size_bytes": db_size,
                "runs_count": runs_count,
                "events_count": events_count,
                "config_count": config_count,
                "connection_ok": True
            }
    except Exception as e:
        logger.error(f"Failed to get database info: {e}")
        return {
            "database_path": DB_PATH,
            "connection_ok": False,
            "error": str(e)
        }
