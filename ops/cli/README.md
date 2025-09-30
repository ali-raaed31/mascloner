# MasCloner Modern CLI

A beautiful, feature-rich command-line interface for managing MasCloner, built with Rich and Typer.

## Features

✨ **Beautiful UI**
- Rich progress bars and spinners
- Color-coded status indicators
- Interactive tables and panels
- Live updating displays

🚀 **Powerful Commands**
- `update` - Update MasCloner with interactive progress
- `status` - Check installation and service health
- `rollback` - Restore from backups

🛡️ **Safety Features**
- Automatic backups before updates
- Health checks after updates
- Interactive confirmations
- Detailed error recovery instructions

## Installation

1. **Install the CLI command:**
   ```bash
   sudo bash /srv/mascloner/ops/scripts/install-cli.sh
   ```

2. **Verify installation:**
   ```bash
   mascloner --help
   ```

## Usage

### Update MasCloner

```bash
# Interactive update with confirmation
sudo mascloner update

# Skip confirmation prompts
sudo mascloner update --yes

# Check for updates without installing
sudo mascloner update --check-only

# Skip backup (not recommended)
sudo mascloner update --skip-backup

# Only update systemd services
sudo mascloner update --services-only

# Only update dependencies
sudo mascloner update --deps-only

# Show what would be done (no changes)
sudo mascloner update --dry-run
```

### Check Status

```bash
# Basic status check
sudo mascloner status

# Detailed information
sudo mascloner status --verbose
```

### Rollback

```bash
# List available backups
sudo mascloner rollback --list

# Interactive rollback
sudo mascloner rollback

# Rollback to specific backup
sudo mascloner rollback /var/backups/mascloner/mascloner_pre_update_20240930_123456.tar.gz

# Skip confirmation
sudo mascloner rollback --yes
```

## Architecture

```
ops/cli/
├── __init__.py           # Package initialization
├── main.py               # CLI entry point
├── utils.py              # Utility functions
├── commands/
│   ├── __init__.py
│   ├── update.py         # Update command
│   ├── status.py         # Status command
│   └── rollback.py       # Rollback command
└── ui/
    ├── __init__.py
    ├── progress.py       # Progress indicators
    ├── tables.py         # Table components
    └── panels.py         # Panel components
```

## Update Process Flow

1. **Prerequisites Check** - Verify system requirements
2. **Update Check** - Compare with remote repository
3. **Backup Creation** - Create timestamped backup
4. **Service Stop** - Gracefully stop all services
5. **Code Update** - Update application files
6. **Dependencies** - Update Python packages
7. **Migrations** - Run database migrations
8. **Service Files** - Update systemd services
9. **Service Start** - Restart all services
10. **Health Check** - Verify everything works

## Configuration

The CLI respects these environment variables:

- `INSTALL_DIR` - MasCloner installation directory (default: `/srv/mascloner`)
- `BACKUP_DIR` - Backup storage directory (default: `/var/backups/mascloner`)
- `MASCLONER_USER` - System user (default: `mascloner`)
- `GIT_REPO` - Git repository URL

## Error Handling

The CLI includes comprehensive error handling:

- **Service failures** - Shows service logs and recovery steps
- **Health check failures** - Provides diagnostic information
- **Backup restoration** - Automatic rollback instructions
- **Interrupt handling** - Clean cancellation with Ctrl+C

## Output Examples

### Update Success
```
╭─────────────────────────────────────────────────────────╮
│            MasCloner Update v2.1.0 → v2.2.0            │
╰─────────────────────────────────────────────────────────╯

✓ Prerequisites check passed
✓ Updates available (12 files changed)
✓ Backup created: /var/backups/mascloner/...

┏━━━━━━━━━━━━━━━┳━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━┓
┃ Service       ┃ Status   ┃ Action            ┃
┡━━━━━━━━━━━━━━━╇━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━┩
│ mascloner-api │ ● active │ ✓ Started         │
│ mascloner-ui  │ ● active │ ✓ Started         │
└───────────────┴──────────┴───────────────────┘

✓ All systems operational
```

### Status Check
```
╭─────────────────────────────────────────────╮
│          MasCloner Status                   │
╰─────────────────────────────────────────────╯

Version: v2.2.0
Installation: /srv/mascloner

┏━━━━━━━━━━━━━━━┳━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━┓
┃ Service       ┃ Status   ┃ Action            ┃
┡━━━━━━━━━━━━━━━╇━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━┩
│ mascloner-api │ ● active │ Running           │
│ mascloner-ui  │ ● active │ Running           │
└───────────────┴──────────┴───────────────────┘

✓ All systems operational
```

## Fallback Mode

If the modern CLI is not available, the `mascloner` command automatically falls back to legacy bash scripts:

- `mascloner update` → `ops/scripts/update.sh`
- `mascloner status` → `ops/scripts/health-check.sh`

This ensures the command always works, even during migration.

## Development

To add new commands:

1. Create a new file in `ops/cli/commands/`
2. Implement a `main()` function with Typer decorators
3. Register it in `ops/cli/main.py`

Example:
```python
# ops/cli/commands/mycommand.py
import typer

def main(
    option: bool = typer.Option(False, "--option", help="Description")
):
    """Command description."""
    # Implementation
```

## Dependencies

- **rich** (13.7.1) - Terminal formatting and UI
- **typer** (0.12.3) - CLI framework

These are automatically installed by the installer script.

## Troubleshooting

### Command not found
```bash
sudo bash /srv/mascloner/ops/scripts/install-cli.sh
```

### Permission denied
The `mascloner` command requires root privileges:
```bash
sudo mascloner update
```

### Import errors
Reinstall dependencies:
```bash
sudo -u mascloner /srv/mascloner/.venv/bin/pip install -r /srv/mascloner/requirements.txt
```

## Migration from Bash Scripts

The new CLI coexists with the old bash scripts:

- **Old:** `sudo bash /srv/mascloner/ops/scripts/update.sh`
- **New:** `sudo mascloner update`

Both work, but the new CLI provides:
- Better user experience
- More features
- Easier maintenance
- Better error handling

## License

Part of the MasCloner project.
