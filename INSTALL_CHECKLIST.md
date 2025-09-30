# MasCloner CLI - Installation Checklist

## ✅ Pre-Installation Checklist

- [ ] MasCloner is installed at `/srv/mascloner`
- [ ] Virtual environment exists at `/srv/mascloner/.venv`
- [ ] You have root/sudo access
- [ ] Internet connection available (for pip install)

## 🚀 Installation Steps

### Step 1: Install Dependencies
```bash
cd /srv/mascloner
sudo -u mascloner .venv/bin/pip install rich==13.7.1 typer==0.12.3
```

**Expected output:**
```
Successfully installed rich-13.7.1 typer-0.12.3
```

- [ ] Dependencies installed successfully

### Step 2: Run Installer
```bash
sudo bash /srv/mascloner/ops/scripts/install-cli.sh
```

**Expected output:**
```
[INFO] Installing MasCloner CLI...
[SUCCESS] ✓ CLI installed successfully!
[SUCCESS] ✓ Dependencies already installed
[SUCCESS] 🎉 Installation complete!
```

- [ ] Installer completed successfully
- [ ] No errors displayed

### Step 3: Verify Installation
```bash
which mascloner
```

**Expected output:**
```
/usr/local/bin/mascloner
```

- [ ] Command found at `/usr/local/bin/mascloner`

### Step 4: Test Help
```bash
mascloner --help
```

**Expected output:**
Rich-formatted help with list of commands

- [ ] Help displays correctly
- [ ] Shows `update`, `status`, `rollback` commands

### Step 5: Test Status (Safe Read-Only)
```bash
sudo mascloner status
```

**Expected output:**
Beautiful table showing services and health checks

- [ ] Status command works
- [ ] Shows current version
- [ ] Displays service status

## 🧪 Optional Testing

### Test Update Check (No Changes)
```bash
sudo mascloner update --check-only
```

- [ ] Checks for updates successfully
- [ ] No changes made to system

### Test Dry Run (No Changes)
```bash
sudo mascloner update --dry-run
```

- [ ] Shows what would be updated
- [ ] No changes made to system

### Test Backup List
```bash
sudo mascloner rollback --list
```

- [ ] Lists existing backups (if any)
- [ ] No errors displayed

## 🎯 First Real Update

When ready to do your first update with the new CLI:

```bash
sudo mascloner update
```

- [ ] Progress bars display correctly
- [ ] Step indicators show progress
- [ ] Tables render properly
- [ ] Colors are visible
- [ ] Update completes successfully

## 🐛 Troubleshooting

### Issue: "mascloner: command not found"
```bash
sudo bash /srv/mascloner/ops/scripts/install-cli.sh
```

### Issue: "No module named 'rich'" or "No module named 'typer'"
```bash
cd /srv/mascloner
sudo -u mascloner .venv/bin/pip install rich==13.7.1 typer==0.12.3
```

### Issue: "Permission denied"
Always use `sudo`:
```bash
sudo mascloner update
```

### Issue: Import errors
Check PYTHONPATH and reinstall:
```bash
sudo bash /srv/mascloner/ops/scripts/install-cli.sh
```

### Fallback to Old Script
If CLI doesn't work, old script is still available:
```bash
sudo bash /srv/mascloner/ops/scripts/update.sh
```

## 📋 Post-Installation

- [ ] Bookmark quick reference: `/srv/mascloner/QUICK_REFERENCE.md`
- [ ] Read full docs: `/srv/mascloner/ops/cli/README.md`
- [ ] Consider enabling tab completion: `mascloner --install-completion`
- [ ] Test rollback feature (if you have backups)

## 🎉 Success Criteria

You'll know it's working when:
- ✅ `mascloner --help` shows beautiful Rich-formatted output
- ✅ `sudo mascloner status` displays colorful tables
- ✅ `sudo mascloner update --dry-run` shows what would be updated
- ✅ Progress bars and spinners animate smoothly
- ✅ Colors are visible and enhance readability
- ✅ No Python import errors

## 📞 Support

If you encounter issues:
1. Check this troubleshooting section
2. Review error messages (they include recovery steps)
3. Use fallback bash scripts if needed
4. Check logs: `journalctl -u mascloner-api`

## 🔄 Rollback

If you need to go back to old bash scripts only:
```bash
sudo rm /usr/local/bin/mascloner
sudo bash /srv/mascloner/ops/scripts/update.sh
```

The old scripts are always available as a fallback!

---

**Happy updating with your beautiful new CLI!** 🎨
