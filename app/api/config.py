"""Configuration management and encryption for MasCloner."""

import os
import logging
from pathlib import Path
from typing import Dict, Any, Optional, List
from dotenv import load_dotenv

# Try to import cryptography, handle gracefully if not available
try:
    from cryptography.fernet import Fernet, InvalidToken
    CRYPTOGRAPHY_AVAILABLE = True
except ImportError:
    CRYPTOGRAPHY_AVAILABLE = False
    # Dummy classes for development
    class Fernet:
        @staticmethod
        def generate_key():
            return b"dummy_key_for_development_only"
        
        def __init__(self, key):
            pass
        
        def encrypt(self, data):
            return b"dummy_encrypted_data"
        
        def decrypt(self, data):
            return b"dummy_decrypted_data"
    
    class InvalidToken(Exception):
        pass

logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()


class ConfigManager:
    """Centralized configuration management for MasCloner."""
    
    def __init__(self, env_file: Optional[str] = None):
        """Initialize configuration manager."""
        if env_file:
            load_dotenv(env_file)
        
        # Initialize encryption
        fernet_key = os.getenv("MASCLONER_FERNET_KEY")
        
        if not CRYPTOGRAPHY_AVAILABLE:
            logger.warning("Cryptography not available, using dummy encryption for development")
            self.fernet = Fernet(b"dummy_key")
        elif not fernet_key:
            raise ValueError("MASCLONER_FERNET_KEY environment variable required")
        else:
            try:
                self.fernet = Fernet(fernet_key.encode())
            except Exception as e:
                raise ValueError(f"Invalid MASCLONER_FERNET_KEY: {e}")
    
    def get_base_config(self) -> Dict[str, Any]:
        """Get base application configuration."""
        return {
            "base_dir": Path(os.getenv("MASCLONER_BASE_DIR", "/srv/mascloner")),
            "db_path": os.getenv("MASCLONER_DB_PATH", "data/mascloner.db"),
            "rclone_conf": os.getenv("MASCLONER_RCLONE_CONF", "etc/rclone.conf"),
            "env_file": os.getenv("MASCLONER_ENV_FILE", "etc/mascloner-sync.env"),
            "log_dir": Path(os.getenv("MASCLONER_LOG_DIR", "logs")),
        }
    
    def get_api_config(self) -> Dict[str, Any]:
        """Get API server configuration."""
        return {
            "host": os.getenv("API_HOST", "127.0.0.1"),
            "port": int(os.getenv("API_PORT", 8787)),
        }
    
    def get_ui_config(self) -> Dict[str, Any]:
        """Get UI server configuration."""
        return {
            "host": os.getenv("UI_HOST", "127.0.0.1"),
            "port": int(os.getenv("UI_PORT", 8501)),
        }
    
    def get_scheduler_config(self) -> Dict[str, Any]:
        """Get scheduler configuration."""
        return {
            "interval_min": int(os.getenv("SYNC_INTERVAL_MIN", 5)),
            "jitter_sec": int(os.getenv("SYNC_JITTER_SEC", 20)),
        }
    
    def get_rclone_config(self) -> Dict[str, Any]:
        """Get rclone performance configuration."""
        return {
            "transfers": int(os.getenv("RCLONE_TRANSFERS", 4)),
            "checkers": int(os.getenv("RCLONE_CHECKERS", 8)),
            "tpslimit": int(os.getenv("RCLONE_TPSLIMIT", 10)),
            "bwlimit": os.getenv("RCLONE_BWLIMIT", "0"),
            "drive_export": os.getenv("RCLONE_DRIVE_EXPORT", "docx,xlsx,pptx"),
            # Use NOTICE by default to reduce per-file INFO logs; stats are still emitted at NOTICE
            "log_level": os.getenv("RCLONE_LOG_LEVEL", "NOTICE"),
            # Tuning and resiliency
            "stats_interval": os.getenv("RCLONE_STATS_INTERVAL", "60s"),
            "buffer_size": os.getenv("RCLONE_BUFFER_SIZE", "16Mi"),
            "drive_chunk_size": os.getenv("RCLONE_DRIVE_CHUNK_SIZE", ""),
            "drive_upload_cutoff": os.getenv("RCLONE_DRIVE_UPLOAD_CUTOFF", ""),
            "retries": int(os.getenv("RCLONE_RETRIES", 5)),
            "retries_sleep": os.getenv("RCLONE_RETRIES_SLEEP", "10s"),
            "low_level_retries": int(os.getenv("RCLONE_LOW_LEVEL_RETRIES", 10)),
            "timeout": os.getenv("RCLONE_TIMEOUT", "5m"),
            # Disabled by default due to potential Drive listing caveats; enable explicitly if desired
            "fast_list": os.getenv("RCLONE_FAST_LIST", "0").lower() in ("1", "true", "yes", "on"),
        }
    
    def get_sync_config(self) -> Dict[str, Any]:
        """Get sync source/destination configuration."""
        return {
            "gdrive_remote": os.getenv("GDRIVE_REMOTE", "gdrive"),
            "gdrive_src": os.getenv("GDRIVE_SRC", ""),
            "nc_remote": os.getenv("NC_REMOTE", "ncwebdav"), 
            "nc_dest_path": os.getenv("NC_DEST_PATH", ""),
            "nc_webdav_url": os.getenv("NC_WEBDAV_URL", ""),
            "nc_user": os.getenv("NC_USER", ""),
            "nc_pass_obscured": os.getenv("NC_PASS_OBSCURED", ""),
        }
    
    def obscure_password(self, password: str) -> str:
        """Encrypt password for storage."""
        try:
            return self.fernet.encrypt(password.encode()).decode()
        except Exception as e:
            logger.error(f"Failed to encrypt password: {e}")
            raise
    
    def reveal_password(self, obscured: str) -> str:
        """Decrypt password for use."""
        try:
            return self.fernet.decrypt(obscured.encode()).decode()
        except InvalidToken:
            logger.error("Invalid encrypted password token")
            raise ValueError("Invalid encrypted password")
        except Exception as e:
            logger.error(f"Failed to decrypt password: {e}")
            raise
    
    def validate_config(self) -> Dict[str, List[str]]:
        """Validate current configuration and return any errors."""
        errors = {}
        
        # Check required paths
        base_config = self.get_base_config()
        if not base_config["db_path"]:
            errors.setdefault("database", []).append("DB_PATH not configured")
        
        if not base_config["rclone_conf"]:
            errors.setdefault("rclone", []).append("RCLONE_CONF not configured")
        
        # Check sync configuration
        sync_config = self.get_sync_config()
        required_sync = ["gdrive_src", "nc_dest_path"]
        for field in required_sync:
            if not sync_config[field]:
                errors.setdefault("sync", []).append(f"{field} not configured")
        
        # Validate network configuration
        try:
            api_config = self.get_api_config()
            port = api_config["port"]
            if not (1 <= port <= 65535):
                errors.setdefault("network", []).append(f"Invalid API port: {port}")
        except ValueError as e:
            errors.setdefault("network", []).append(f"Invalid API port: {e}")
        
        try:
            ui_config = self.get_ui_config()
            port = ui_config["port"]
            if not (1 <= port <= 65535):
                errors.setdefault("network", []).append(f"Invalid UI port: {port}")
        except ValueError as e:
            errors.setdefault("network", []).append(f"Invalid UI port: {e}")
        
        return errors


# Global configuration instance
try:
    # Set a dummy key for development if not provided
    if not os.getenv("MASCLONER_FERNET_KEY") and not CRYPTOGRAPHY_AVAILABLE:
        os.environ["MASCLONER_FERNET_KEY"] = "dummy_development_key"
    
    config = ConfigManager()
except Exception as e:
    logger.warning(f"Failed to initialize configuration: {e}")
    config = None


# Configuration convenience functions
def get_base_dir() -> Path:
    """Get base directory path."""
    return config.get_base_config()["base_dir"] if config else Path("/srv/mascloner")


def get_db_path() -> str:
    """Get database file path."""
    return config.get_base_config()["db_path"] if config else "data/mascloner.db"


def get_log_dir() -> Path:
    """Get log directory path."""
    return config.get_base_config()["log_dir"] if config else Path("logs")


def get_rclone_conf_path() -> str:
    """Get rclone configuration file path."""
    return config.get_base_config()["rclone_conf"] if config else "etc/rclone.conf"


def resolve_conflict_filename(original_path: str, dest_dir: str) -> str:
    """Generate conflict filename with suffix when file already exists."""
    dest_path = Path(dest_dir) / Path(original_path).name
    
    if not dest_path.exists():
        return str(dest_path)
    
    # File exists, generate conflict name
    stem = dest_path.stem
    suffix = dest_path.suffix
    parent = dest_path.parent
    
    counter = 1
    while True:
        conflict_name = f"{stem}-conflict({counter}){suffix}"
        conflict_path = parent / conflict_name
        
        if not conflict_path.exists():
            return str(conflict_path)
        
        counter += 1
        if counter > 1000:  # Prevent infinite loop
            raise RuntimeError(f"Too many conflicts for file: {original_path}")


def generate_fernet_key() -> str:
    """Generate a new Fernet encryption key."""
    return Fernet.generate_key().decode()


# Configuration validation
def validate_paths(paths_config: Dict[str, Any]) -> List[str]:
    """Validate file and directory paths in configuration."""
    errors = []
    
    for key, path_value in paths_config.items():
        if not path_value:
            continue
            
        path_obj = Path(path_value)
        
        # Check directory existence for *_dir keys
        if key.endswith('_dir'):
            if not path_obj.exists():
                errors.append(f"Directory does not exist: {path_value}")
            elif not path_obj.is_dir():
                errors.append(f"Path is not a directory: {path_value}")
        
        # Check critical files
        elif key in ['db_path']:
            # DB file can be created, just check parent directory
            if not path_obj.parent.exists():
                errors.append(f"DB parent directory does not exist: {path_obj.parent}")
        elif key in ['rclone_conf']:
            # rclone.conf should exist for production use
            if not path_obj.exists():
                errors.append(f"rclone config file does not exist: {path_value}")
    
    return errors
