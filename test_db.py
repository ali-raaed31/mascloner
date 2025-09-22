#!/usr/bin/env python3
"""Test script for database initialization and configuration."""

import os
import sys
from pathlib import Path

# Add the app directory to the Python path
sys.path.insert(0, str(Path(__file__).parent))

# Set up a test environment
os.environ["MASCLONER_DB_PATH"] = "data/test_mascloner.db"
os.environ["MASCLONER_FERNET_KEY"] = "test_key_not_for_production_" + "A" * 16

def test_database():
    """Test database initialization."""
    try:
        from app.api.db import init_db, test_db_connection, get_db_info
        
        print("Testing database initialization...")
        init_db()
        print("✓ Database initialized successfully")
        
        print("\nTesting database connection...")
        if test_db_connection():
            print("✓ Database connection successful")
        else:
            print("✗ Database connection failed")
            return False
        
        print("\nGetting database info...")
        info = get_db_info()
        print(f"✓ Database info: {info}")
        
        return True
        
    except Exception as e:
        print(f"✗ Database test failed: {e}")
        return False


def test_config():
    """Test configuration management."""
    try:
        # Check if cryptography is available
        try:
            import cryptography
            from app.api.config import generate_fernet_key, ConfigManager
            
            print("\nTesting configuration...")
            
            # Generate a proper Fernet key
            key = generate_fernet_key()
            os.environ["MASCLONER_FERNET_KEY"] = key
            
            print("✓ Generated Fernet key")
        except ImportError:
            print("\nSkipping configuration test - cryptography not installed")
            print("ℹ This is expected in development environment")
            return True
        
        # Test configuration manager
        config_mgr = ConfigManager()
        print("✓ Configuration manager initialized")
        
        # Test configuration sections
        base_config = config_mgr.get_base_config()
        print(f"✓ Base config: {base_config}")
        
        api_config = config_mgr.get_api_config()
        print(f"✓ API config: {api_config}")
        
        # Test encryption/decryption
        test_password = "test_password_123"
        encrypted = config_mgr.obscure_password(test_password)
        decrypted = config_mgr.reveal_password(encrypted)
        
        if decrypted == test_password:
            print("✓ Password encryption/decryption working")
        else:
            print("✗ Password encryption/decryption failed")
            return False
        
        # Test validation
        errors = config_mgr.validate_config()
        print(f"✓ Configuration validation: {errors}")
        
        return True
        
    except Exception as e:
        print(f"✗ Configuration test failed: {e}")
        return False


def test_models():
    """Test database models."""
    try:
        from app.api.models import ConfigKV, Run, FileEvent
        from app.api.db import get_db_session
        from datetime import datetime
        from sqlalchemy import select
        
        print("\nTesting database models...")
        
        with get_db_session() as db:
            # Clean up any existing test data
            existing_config = db.execute(select(ConfigKV).where(ConfigKV.key == "test_key")).scalar_one_or_none()
            if existing_config:
                db.delete(existing_config)
                db.commit()
            
            # Test ConfigKV
            config_item = ConfigKV(key="test_key", value="test_value")
            db.add(config_item)
            db.commit()
            print("✓ ConfigKV model works")
            
            # Test Run
            run = Run(
                status="running",
                num_added=5,
                num_updated=2,
                bytes_transferred=1024,
                log_path="/tmp/test.log"
            )
            db.add(run)
            db.flush()  # Get the ID
            print("✓ Run model works")
            
            # Test FileEvent
            event = FileEvent(
                run_id=run.id,
                action="added",
                file_path="/test/file.txt",
                file_size=512,
                message="Test file added"
            )
            db.add(event)
            db.commit()
            print("✓ FileEvent model works")
            
            # Test relationships
            db.refresh(run)
            assert len(run.events) == 1
            assert run.events[0].file_path == "/test/file.txt"
            print("✓ Model relationships work")
        
        return True
        
    except Exception as e:
        print(f"✗ Models test failed: {e}")
        return False


def main():
    """Run all tests."""
    print("MasCloner Database and Configuration Tests")
    print("=" * 50)
    
    success = True
    
    # Test database
    if not test_database():
        success = False
    
    # Test configuration
    if not test_config():
        success = False
    
    # Test models
    if not test_models():
        success = False
    
    print("\n" + "=" * 50)
    if success:
        print("✓ All tests passed!")
        
        # Clean up test database
        test_db_path = Path("data/test_mascloner.db")
        if test_db_path.exists():
            test_db_path.unlink()
            print("✓ Test database cleaned up")
    else:
        print("✗ Some tests failed!")
        sys.exit(1)


if __name__ == "__main__":
    main()
