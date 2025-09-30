# Upgrading to the Modern MasCloner CLI

Welcome to the new MasCloner CLI! This guide will help you migrate from the bash scripts to the beautiful new Rich-based CLI.

## 🎨 What's New?

### Beautiful UI
- **Rich progress bars** - See exactly what's happening during updates
- **Live status tables** - Service status, health checks, file changes
- **Color-coded output** - Errors in red, success in green, info in blue
- **Interactive prompts** - Confirm actions with clear context
- **Spinners & animations** - Visual feedback for long operations

### Better Features
- **Multiple commands** - `update`, `status`, `rollback` all in one CLI
- **Smart updates** - Only updates what changed
- **Dry run mode** - See what would happen without making changes
- **Selective updates** - Update only services or only dependencies
- **Better errors** - Clear recovery instructions when things go wrong
- **Automatic backups** - Always creates a backup before updates

### Improved Safety
- **Health checks** - Verifies everything works after updates
- **Rollback command** - Easy restoration from backups
- **Service verification** - Ensures services start correctly
- **Detailed logging** - Know exactly what happened

## 📦 Installation

### Step 1: Install Dependencies

The new CLI requires Rich and Typer (already added to `requirements.txt`):

```bash
cd /srv/mascloner
sudo -u mascloner .venv/bin/pip install rich==13.7.1 typer==0.12.3
```

### Step 2: Install the CLI Command

Run the installer script:

```bash
sudo bash /srv/mascloner/ops/scripts/install-cli.sh
```

This will:
- Install dependencies if needed
- Create a symlink at `/usr/local/bin/mascloner`
- Make the command available system-wide

### Step 3: Verify Installation

```bash
mascloner --help
```

You should see the beautiful Rich-formatted help output!

## 🚀 Usage

### Before (Old Bash Scripts)

```bash
# Update
sudo bash /srv/mascloner/ops/scripts/update.sh

# Health check
sudo bash /srv/mascloner/ops/scripts/health-check.sh
```

### After (New CLI)

```bash
# Update (with beautiful progress bars!)
sudo mascloner update

# Check status
sudo mascloner status

# List backups
sudo mascloner rollback --list

# Rollback to a backup
sudo mascloner rollback
```

## 🎯 Command Examples

### Update Commands

```bash
# Interactive update (asks for confirmation)
sudo mascloner update

# Skip confirmation
sudo mascloner update --yes

# Just check if updates are available
sudo mascloner update --check-only

# Preview what would happen (no changes)
sudo mascloner update --dry-run

# Update only systemd service files
sudo mascloner update --services-only

# Update only Python dependencies
sudo mascloner update --deps-only

# Skip backup creation (not recommended)
sudo mascloner update --skip-backup
```

### Status Commands

```bash
# Basic status
sudo mascloner status

# Detailed information
sudo mascloner status --verbose
```

### Rollback Commands

```bash
# List all backups
sudo mascloner rollback --list

# Interactive rollback (choose from list)
sudo mascloner rollback

# Rollback to specific backup
sudo mascloner rollback /var/backups/mascloner/mascloner_pre_update_20240930_123456.tar.gz

# Skip confirmation
sudo mascloner rollback --yes
```

## 🔄 Migration Timeline

### Phase 1: Both Available (Current)
- Old bash scripts still work
- New CLI available as `mascloner` command
- Use whichever you prefer

### Phase 2: Recommended (After testing)
- New CLI is recommended
- Old scripts remain as fallback
- Documentation uses new CLI

### Phase 3: Default (Future)
- New CLI is the default
- Old scripts kept for emergencies
- All docs reference new CLI

## 📊 Feature Comparison

| Feature | Old Bash Scripts | New CLI |
|---------|-----------------|---------|
| Progress indicators | Basic text | Rich progress bars |
| Service status | Text output | Beautiful tables |
| Error handling | Text messages | Color-coded + recovery |
| Health checks | Basic | Comprehensive |
| Backups | Manual | Automatic |
| Rollback | Manual process | Interactive command |
| Dry run | Not available | ✓ Available |
| Selective updates | Not available | ✓ Available |
| Status command | Basic health check | Full status dashboard |

## 🎨 Visual Examples

### Update Output

The old way:
```
[INFO] Starting MasCloner update process...
[INFO] Checking prerequisites...
[SUCCESS] Prerequisites check passed
[INFO] Creating backup...
```

The new way:
```
╭─────────────────────────────────────────────────────────╮
│            MasCloner Update v2.1.0 → v2.2.0            │
╰─────────────────────────────────────────────────────────╯

✓ Check prerequisites
⠋ Creating backup...

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 45% 00:32

┏━━━━━━━━━━━━━━━┳━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━┓
┃ Service       ┃ Status   ┃ Action            ┃
┡━━━━━━━━━━━━━━━╇━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━┩
│ mascloner-api │ stopped  │ ⏸  Waiting       │
│ mascloner-ui  │ stopped  │ ⏸  Waiting       │
└───────────────┴──────────┴───────────────────┘
```

### Status Output

The new status command shows:
- Current version
- Service status with icons
- Health check results
- Installation paths

All in beautiful, color-coded tables!

## 🛠 Troubleshooting

### "mascloner: command not found"

Re-run the installer:
```bash
sudo bash /srv/mascloner/ops/scripts/install-cli.sh
```

### Import errors

Install dependencies:
```bash
cd /srv/mascloner
sudo -u mascloner .venv/bin/pip install rich typer
```

### Permission denied

Always use `sudo`:
```bash
sudo mascloner update
```

### Want to use old scripts?

They're still available:
```bash
sudo bash /srv/mascloner/ops/scripts/update.sh
```

## 🎁 Bonus Features

### Tab Completion

Typer supports shell completion! Enable it with:
```bash
mascloner --install-completion
```

### Help System

Every command has detailed help:
```bash
mascloner --help
mascloner update --help
mascloner status --help
mascloner rollback --help
```

### Non-Interactive Mode

Perfect for automation:
```bash
sudo mascloner update --yes --skip-backup
```

## 🚦 Getting Started

1. **Install the CLI** (takes 30 seconds)
   ```bash
   sudo bash /srv/mascloner/ops/scripts/install-cli.sh
   ```

2. **Try the status command** (safe, read-only)
   ```bash
   sudo mascloner status
   ```

3. **Check for updates** (just checks, doesn't update)
   ```bash
   sudo mascloner update --check-only
   ```

4. **Try a dry run** (see what would happen)
   ```bash
   sudo mascloner update --dry-run
   ```

5. **Do your first update!**
   ```bash
   sudo mascloner update
   ```

Enjoy the beautiful new experience! 🎉

## 📚 Documentation

- Full CLI documentation: `/srv/mascloner/ops/cli/README.md`
- Command reference: `mascloner --help`
- Update guide: This file!

## 💬 Feedback

The new CLI is designed to make your life easier. If you have suggestions or find issues:
1. The old bash scripts remain available as a fallback
2. Report issues or suggestions to the development team
3. Contribute improvements to the CLI code

---

**Happy updating!** 🚀
