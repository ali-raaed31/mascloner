# MasCloner CLI - Quick Reference

## Installation

```bash
sudo bash /srv/mascloner/ops/scripts/install-cli.sh
```

## Commands

### Update
```bash
sudo mascloner update              # Interactive update
sudo mascloner update -y           # Skip confirmations
sudo mascloner update --check-only # Just check for updates
sudo mascloner update --dry-run    # Preview without changes
```

### Status
```bash
sudo mascloner status              # Basic status
sudo mascloner status -v           # Detailed status
```

### Rollback
```bash
sudo mascloner rollback --list     # List backups
sudo mascloner rollback            # Interactive rollback
```

## Help
```bash
mascloner --help                   # Show all commands
mascloner update --help            # Update command help
mascloner status --help            # Status command help
mascloner rollback --help          # Rollback command help
```

## Common Tasks

| Task | Command |
|------|---------|
| Check if updates available | `sudo mascloner update --check-only` |
| Update MasCloner | `sudo mascloner update` |
| Quick status check | `sudo mascloner status` |
| View backups | `sudo mascloner rollback --list` |
| Restore from backup | `sudo mascloner rollback` |
| Preview update | `sudo mascloner update --dry-run` |
| Non-interactive update | `sudo mascloner update -y` |

## Troubleshooting

| Issue | Solution |
|-------|----------|
| Command not found | `sudo bash /srv/mascloner/ops/scripts/install-cli.sh` |
| Import errors | `sudo -u mascloner /srv/mascloner/.venv/bin/pip install rich typer` |
| Permission denied | Always use `sudo mascloner ...` |
| Want old scripts | `sudo bash /srv/mascloner/ops/scripts/update.sh` |

## What Gets Updated

- ✅ Application code (app/, ops/)
- ✅ Python dependencies (requirements.txt)
- ✅ SystemD service files
- ✅ Database migrations
- ❌ Configuration (etc/, .env) - preserved
- ❌ Data (data/) - preserved
- ❌ Logs - preserved

## Safety Features

- 🛡️ Automatic backup before updates
- 🔍 Health checks after updates
- ✅ Service verification
- 🔙 Easy rollback command
- 🔒 Requires root privileges

## Logs Location

```bash
# Service logs
journalctl -u mascloner-api -f
journalctl -u mascloner-ui -f

# Application logs
tail -f /srv/mascloner/logs/*.log
```

---
For full documentation, see: `/srv/mascloner/ops/cli/README.md`
