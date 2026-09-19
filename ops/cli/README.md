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
release_archive=/path/to/qualified-release.tar.gz
release_sha256=REPLACE_WITH_PUBLISHED_SHA256

# Validate the release and installed Python without changing the installation
sudo env MASCLONER_RELEASE_ARCHIVE="$release_archive" \
  MASCLONER_RELEASE_SHA256="$release_sha256" mascloner update --check-only

# Install the complete release with a verified recovery bundle
sudo env MASCLONER_RELEASE_ARCHIVE="$release_archive" \
  MASCLONER_RELEASE_SHA256="$release_sha256" mascloner update --yes
```

The `--skip-backup`, `--services-only`, and `--deps-only` flags are rejected for
verified updates. An installation still at `7f22b48` needs the one-time bridge
in [the v3.2.0 upgrade guide](../../docs/releases/v3.2.0.md) first.

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

If the modern CLI is missing, the wrapper can still run the legacy status
check. Updates fail without changing files and direct the operator to the
verified bridge:

- `mascloner update` → `ops/scripts/update.sh` → fails safely without the CLI
- `mascloner status` → `ops/scripts/health-check.sh`

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

On v3.2.0 and later, `ops/scripts/update.sh` forwards to the same verified CLI
updater. The old clone-based script in an installed v3.0 release cannot be
changed retroactively; use the one-time bridge before invoking the v3.2 CLI.

## License

Part of the MasCloner project.
