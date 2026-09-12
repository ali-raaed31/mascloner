"""InstallationRoot fixture builder and manager.

Creates and manages completely isolated directory structures containing
representative configuration, SQLite databases, rclone.conf, and runtime logs.
Ensures no test touches caller home directory or live /srv/mascloner configuration.
"""

from __future__ import annotations

import os
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

import dotenv
from cryptography.fernet import Fernet
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api.models import Base, ConfigKV, FileEvent, Run
from tests.harness.fake_rclone import FakeRcloneController


class InstallationRoot:
    """An isolated installation filesystem root for characterization tests."""

    def __init__(self, temp_dir: Optional[Path] = None):
        if temp_dir is None:
            self._temp_dir_obj = tempfile.TemporaryDirectory(prefix="mascloner_test_")
            self.base_dir = Path(self._temp_dir_obj.name).resolve()
        else:
            self._temp_dir_obj = None
            self.base_dir = temp_dir.resolve()

        self.etc_dir = self.base_dir / "etc"
        self.data_dir = self.base_dir / "data"
        self.log_dir = self.base_dir / "logs"
        self.bin_dir = self.base_dir / "bin"

        self.rclone_conf_path = self.etc_dir / "rclone.conf"
        self.env_file_path = self.etc_dir / "mascloner-sync.env"
        self.root_env_path = self.base_dir / ".env"
        self.db_path = self.data_dir / "mascloner.db"

        # Fake rclone controller
        self.fake_rclone = FakeRcloneController(self.base_dir)

        # Ensure directories exist
        for d in (self.etc_dir, self.data_dir, self.log_dir, self.bin_dir):
            d.mkdir(parents=True, exist_ok=True)

        self.fake_rclone.install()
        self.fernet_key: str = Fernet.generate_key().decode()

    def get_env_dict(self, extra_env: Optional[Dict[str, str]] = None) -> Dict[str, str]:
        """Return environment dictionary pointing to this isolated installation."""
        env: Dict[str, str] = {}
        if self.root_env_path.exists():
            parsed_vals = dotenv.dotenv_values(self.root_env_path)
            for k, v in parsed_vals.items():
                if v is not None:
                    env[k] = str(v)

        env.update(
            {
                "MASCLONER_BASE_DIR": str(self.base_dir),
                "MASCLONER_DB_PATH": str(self.db_path),
                "MASCLONER_RCLONE_CONF": str(self.rclone_conf_path.relative_to(self.base_dir)),
                "MASCLONER_ENV_FILE": str(self.env_file_path.relative_to(self.base_dir)),
                "MASCLONER_LOG_DIR": str(self.log_dir),
                "MASCLONER_FERNET_KEY": self.fernet_key,
                "PATH": f"{self.bin_dir}:{os.environ.get('PATH', '')}",
                "FAKE_RCLONE_CONTROL_FILE": str(self.fake_rclone.control_file),
                "FAKE_RCLONE_INVOCATIONS_FILE": str(self.fake_rclone.invocations_file),
            }
        )
        if extra_env:
            env.update(extra_env)
        return env

    def init_database(self) -> None:
        """Create database tables and stamp schema."""
        engine = create_engine(
            f"sqlite:///{self.db_path}",
            future=True,
            connect_args={"check_same_thread": False},
        )
        Base.metadata.create_all(bind=engine)
        engine.dispose()

    def create_fresh(self) -> InstallationRoot:
        """Configure fresh installation state."""
        self.init_database()

        # Write minimal rclone.conf
        self.rclone_conf_path.write_text(
            "[gdrive]\ntype = drive\nscope = drive.readonly\n\n[ncwebdav]\ntype = webdav\nvendor = nextcloud\n",
            encoding="utf-8",
        )

        # Write .env
        env_content = f"""MASCLONER_BASE_DIR={self.base_dir}
MASCLONER_DB_PATH={self.db_path}
MASCLONER_RCLONE_CONF={self.rclone_conf_path.relative_to(self.base_dir)}
MASCLONER_ENV_FILE={self.env_file_path.relative_to(self.base_dir)}
MASCLONER_LOG_DIR={self.log_dir}
MASCLONER_FERNET_KEY={self.fernet_key}
MASCLONER_AUTH_ENABLED=0
SYNC_INTERVAL_MIN=5
SYNC_JITTER_SEC=20
RCLONE_TRANSFERS=8
RCLONE_CHECKERS=16
RCLONE_TPSLIMIT=25
RCLONE_BWLIMIT=0
GDRIVE_REMOTE=gdrive
GDRIVE_SRC=FreshSource
NC_REMOTE=ncwebdav
NC_DEST_PATH=FreshDestination
"""
        self.root_env_path.write_text(env_content, encoding="utf-8")
        self.env_file_path.write_text(env_content, encoding="utf-8")
        return self

    def create_legacy(
        self,
        legacy_fernet_key: Optional[str] = None,
        include_stale_running: bool = True,
    ) -> InstallationRoot:
        """Configure a representative legacy installation with encrypted values and legacy statuses."""
        if legacy_fernet_key:
            self.fernet_key = legacy_fernet_key
        else:
            self.fernet_key = Fernet.generate_key().decode()

        f = Fernet(self.fernet_key.encode())
        encrypted_client_id = f.encrypt(b"legacy-google-client-id-12345.apps.googleusercontent.com").decode()
        encrypted_client_secret = f.encrypt(b"legacy-google-client-secret-XYZ-SECRET").decode()

        self.init_database()

        # Seed legacy SQLite database with legacy statuses and configs
        engine = create_engine(
            f"sqlite:///{self.db_path}",
            future=True,
            connect_args={"check_same_thread": False},
        )
        Session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
        with Session() as session:
            # Legacy ConfigKV items
            session.add_all(
                [
                    ConfigKV(key="interval_min", value="10"),
                    ConfigKV(key="jitter_sec", value="30"),
                    ConfigKV(key="gdrive_src", value="LegacyFolder"),
                    ConfigKV(key="nc_dest_path", value="LegacyBackups"),
                ]
            )

            now = datetime.now(timezone.utc)
            # Legacy runs with legacy statuses: success, error, stopped, partial, and running
            run_success = Run(
                status="success",  # Legacy status
                started_at=now,
                finished_at=now,
                num_added=15,
                num_updated=2,
                bytes_transferred=1048576,
                errors=0,
                log_path=str(self.log_dir / "legacy-run-1.log"),
            )
            run_error = Run(
                status="error",  # Legacy status
                started_at=now,
                finished_at=now,
                num_added=0,
                num_updated=0,
                bytes_transferred=0,
                errors=3,
                log_path=str(self.log_dir / "legacy-run-2.log"),
            )
            run_stopped = Run(
                status="stopped",  # Legacy status
                started_at=now,
                finished_at=now,
                num_added=5,
                num_updated=0,
                bytes_transferred=512000,
                errors=0,
                log_path=str(self.log_dir / "legacy-run-3.log"),
            )
            run_partial = Run(
                status="partial",  # Legacy status
                started_at=now,
                finished_at=now,
                num_added=7,
                num_updated=1,
                bytes_transferred=700000,
                errors=1,
                log_path=str(self.log_dir / "legacy-run-4.log"),
            )
            session.add_all([run_success, run_error, run_stopped, run_partial])

            if include_stale_running:
                run_running = Run(
                    status="running",  # Stale run for recovery testing
                    started_at=now,
                    num_added=1,
                    num_updated=0,
                    bytes_transferred=10000,
                    errors=0,
                    log_path=str(self.log_dir / "legacy-run-5.log"),
                )
                session.add(run_running)

            session.commit()

            # Add legacy file events
            session.add_all(
                [
                    FileEvent(
                        run_id=run_success.id,
                        timestamp=now,
                        action="added",
                        file_path="LegacyFolder/file1.txt",
                        file_size=1024,
                        message="Copied (new)",
                    ),
                    FileEvent(
                        run_id=run_success.id,
                        timestamp=now,
                        action="updated",
                        file_path="LegacyFolder/file2.txt",
                        file_size=2048,
                        message="Copied (replaced)",
                    ),
                    FileEvent(
                        run_id=run_error.id,
                        timestamp=now,
                        action="error",
                        file_path="LegacyFolder/bad.txt",
                        file_size=0,
                        message="Failed to copy",
                    ),
                ]
            )
            session.commit()
        engine.dispose()

        # Legacy rclone.conf
        rclone_conf_content = """[gdrive]
type = drive
scope = drive.readonly
token = {"access_token":"ya29.legacy_token_123","token_type":"Bearer","refresh_token":"1//legacy_refresh_abc","expiry":"2026-12-31T23:59:59Z"}
team_drive = 

[ncwebdav]
type = webdav
url = https://nextcloud.legacy.example.com/remote.php/dav/files/admin/
vendor = nextcloud
user = admin
pass = obscured_legacy_pass_999
"""
        self.rclone_conf_path.write_text(rclone_conf_content, encoding="utf-8")

        # Write legacy .env with Fernet encrypted values and auth enabled
        env_content = f"""MASCLONER_BASE_DIR={self.base_dir}
MASCLONER_DB_PATH={self.db_path}
MASCLONER_RCLONE_CONF={self.rclone_conf_path.relative_to(self.base_dir)}
MASCLONER_ENV_FILE={self.env_file_path.relative_to(self.base_dir)}
MASCLONER_LOG_DIR={self.log_dir}
MASCLONER_FERNET_KEY={self.fernet_key}
MASCLONER_AUTH_ENABLED=1
MASCLONER_AUTH_USERNAME=legacy_admin
MASCLONER_AUTH_PASSWORD=legacy_secret_password_456
GDRIVE_OAUTH_CLIENT_ID={encrypted_client_id}
GDRIVE_OAUTH_CLIENT_SECRET={encrypted_client_secret}
GDRIVE_REMOTE=gdrive
GDRIVE_SRC=LegacyFolder
NC_REMOTE=ncwebdav
NC_DEST_PATH=LegacyBackups
NC_WEBDAV_URL=https://nextcloud.legacy.example.com/remote.php/dav/files/admin/
NC_USER=admin
NC_PASS_OBSCURED=obscured_legacy_pass_999
"""
        self.root_env_path.write_text(env_content, encoding="utf-8")
        self.env_file_path.write_text(env_content, encoding="utf-8")
        return self

    def cleanup(self) -> None:
        """Safely destroy the temporary installation."""
        if self._temp_dir_obj is not None:
            self._temp_dir_obj.cleanup()
        elif self.base_dir.exists():
            shutil.rmtree(self.base_dir, ignore_errors=True)
