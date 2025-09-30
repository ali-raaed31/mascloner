#!/usr/bin/env python3
"""Setup development environment for MasCloner."""

import os
import sys
from pathlib import Path

def setup_dev_environment():
    """Set up development environment with dummy configurations."""
    
    print("Setting up MasCloner development environment...")
    
    # Create necessary directories
    dirs = ["data", "etc", "logs"]
    for dir_name in dirs:
        Path(dir_name).mkdir(exist_ok=True)
        print(f"✓ Created directory: {dir_name}")
    
    # Create dummy rclone config
    rclone_config = """[gdrive]
type = drive
scope = drive.readonly
token = {"access_token":"dummy_token","token_type":"Bearer","refresh_token":"dummy_refresh","expiry":"2024-01-01T00:00:00.000Z"}

[ncwebdav]
type = webdav
url = https://cloud.example.com/remote.php/dav/files/username/
vendor = nextcloud
user = username
pass = obscured_password
"""
    
    rclone_conf_path = Path("etc/rclone.conf")
    with open(rclone_conf_path, 'w') as f:
        f.write(rclone_config)
    
    # Set secure permissions (Linux only)
    if os.name != 'nt':
        os.chmod(rclone_conf_path, 0o600)
    
    print(f"✓ Created dummy rclone config: {rclone_conf_path}")
    
    # Create development .env with proper encryption key
    env_content = """# MasCloner Development Configuration

# Application Base
MASCLONER_BASE_DIR=.
MASCLONER_DB_PATH=data/mascloner.db
MASCLONER_RCLONE_CONF=etc/rclone.conf
MASCLONER_ENV_FILE=etc/mascloner-sync.env
MASCLONER_LOG_DIR=logs

# Encryption key (development only - generate new for production!)
MASCLONER_FERNET_KEY=development_key_not_for_production_use_123456789012345678901234567890123456789012345678901234567890

# API/UI Binding
API_HOST=127.0.0.1
API_PORT=8787
UI_HOST=127.0.0.1
UI_PORT=8501

# Scheduler Defaults
SYNC_INTERVAL_MIN=5
SYNC_JITTER_SEC=20

# rclone Performance Defaults
RCLONE_TRANSFERS=4
RCLONE_CHECKERS=8
RCLONE_TPSLIMIT=10
RCLONE_BWLIMIT=0
RCLONE_DRIVE_EXPORT=docx,xlsx,pptx
RCLONE_LOG_LEVEL=INFO

# Sync Configuration (dummy values for development)
GDRIVE_REMOTE=gdrive
GDRIVE_SRC=TestFolder
NC_REMOTE=ncwebdav
NC_DEST_PATH=Backups/GoogleDrive
NC_WEBDAV_URL=https://cloud.example.com/remote.php/dav/files/username/
NC_USER=username
NC_PASS_OBSCURED=dummy_obscured_password
"""
    
    env_path = Path(".env")
    with open(env_path, 'w') as f:
        f.write(env_content)
    
    print(f"✓ Created development .env: {env_path}")
    
    # Create proper Fernet key for production
    try:
        from cryptography.fernet import Fernet
        production_key = Fernet.generate_key().decode()
        
        production_env = env_content.replace(
            "development_key_not_for_production_use_123456789012345678901234567890123456789012345678901234567890",
            production_key
        )
        
        prod_env_path = Path(".env.production")
        with open(prod_env_path, 'w') as f:
            f.write(production_env)
        
        print(f"✓ Created production .env template: {prod_env_path}")
        print("  (Use this for actual deployment)")
        
    except ImportError:
        print("⚠ cryptography not available - production .env not created")
        print("  Install cryptography package for production deployment")
    
    print("\n" + "="*50)
    print("✓ Development environment setup complete!")
    print("\nNext steps:")
    print("1. Install dependencies: pip install -r requirements.txt")
    print("2. Run API server: python -m app.api.main")
    print("3. In another terminal, run UI: streamlit run app/ui/Home.py")
    print("\nNote: This is a development setup with dummy configurations.")
    print("For production, configure real rclone remotes and use .env.production")


if __name__ == "__main__":
    setup_dev_environment()
