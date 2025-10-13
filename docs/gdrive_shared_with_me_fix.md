# Google Drive "Shared with me" vs "My Drive" Fix

## Problem Summary

MasCloner was failing to sync folders from Google Drive with error:
```
error reading source root directory: directory not found
```

Manual `rclone` commands worked perfectly, but Python subprocess execution failed.

## Root Cause

The `--drive-shared-with-me` flag was **hard-coded** in `app/api/rclone_runner.py` line 199, which restricts rclone to ONLY access the "Shared with me" folder in Google Drive.

When users tried to sync folders from "My Drive", rclone couldn't see them because of this restriction.

### Why Manual Commands Worked

Manual rclone commands didn't include the `--drive-shared-with-me` flag, so they had full access to both:
- My Drive
- Shared with me

### Why Python Subprocess Failed

The Python code automatically added `--drive-shared-with-me` to every sync command, restricting access.

## Solution Implemented

### 1. Made the Flag Optional (Backend)

**Files Modified:**
- `app/api/schemas.py` - Added `gdrive_shared_with_me` field to `ConfigRequest`
- `app/api/rclone_runner.py` - Made flag conditional via `shared_with_me` parameter
- `app/api/scheduler.py` - Pass config value to `run_sync()`

**Default Behavior:**
- `gdrive_shared_with_me = false` (default) → Access both "My Drive" AND "Shared with me"
- `gdrive_shared_with_me = true` → Restrict to "Shared with me" only

### 2. Added UI Control (Frontend)

**File Modified:**
- `app/ui/pages/4_Setup_Wizard.py`

**UI Changes:**
- Added checkbox: "🔒 Restrict to 'Shared with me' folder only"
- Added info messages explaining the behavior
- Shows current mode in status summary

## How to Use

### For "My Drive" Folders (Default - Most Common)

1. Go to Setup Wizard → Sync Paths
2. **Leave checkbox UNCHECKED** (default)
3. Select your source folder
4. Save

✅ Sync will work for both "My Drive" and "Shared with me" folders

### For "Shared with me" Folders Only (Special Case)

1. Go to Setup Wizard → Sync Paths
2. **Check the box** "🔒 Restrict to 'Shared with me' folder only"
3. Select your source folder from shared items
4. Save

⚠️ Sync will ONLY work for "Shared with me" folders, not "My Drive"

## Testing Results

Test script confirmed subprocess execution works correctly:

```bash
$ sudo -u mascloner python3 /srv/mascloner/test_rclone_subprocess.py
Return code: 0
NOTICE: 2536103 Rev.1 - BASRAH MAS - Tuba & PS1 GTG.pdf: Skipped copy as --dry-run is set (size 687.523Ki)
Transferred: 687.523 KiB / 687.523 KiB, 100%
```

## Technical Details

### rclone Flag Behavior

According to [rclone documentation](https://rclone.org/drive/#drive-shared-with-me):

> `--drive-shared-with-me`: Only show files that are shared with me. Instructs rclone to operate on your "Shared with me" folder

**Without the flag:** rclone can access the entire drive (My Drive + Shared)
**With the flag:** rclone is restricted to "Shared with me" only

### Configuration Storage

The setting is stored in the database as:
```python
gdrive_shared_with_me: "true" | "false"  # String in DB
```

And converted to boolean when passed to rclone:
```python
shared_with_me = sync_config.get("gdrive_shared_with_me", "false").lower() == "true"
```

## Deployment

1. Restart the API service:
   ```bash
   sudo systemctl restart mascloner-api
   ```

2. Check status:
   ```bash
   sudo systemctl status mascloner-api
   ```

3. Test sync from UI or trigger manually:
   ```bash
   curl -X POST http://localhost:8787/runs
   ```

## Future Considerations

- Most users will use "My Drive" (default behavior)
- The checkbox provides clarity for the special case of shared folders
- The flag is now documented and intentional, not hidden
- Existing configs will default to `false` (safe behavior)

## Related Files

- `app/api/rclone_runner.py` - Sync execution logic
- `app/api/schemas.py` - API request models
- `app/api/scheduler.py` - Scheduled sync jobs
- `app/ui/pages/4_Setup_Wizard.py` - User configuration interface
- `test_rclone_subprocess.py` - Test script for debugging

## Lessons Learned

1. Always check for backend-specific flags that might restrict functionality
2. Test manual commands vs. automated commands for environment differences
3. Hard-coded flags can cause unexpected behavior - make them configurable
4. Document edge cases in the UI for user clarity
5. rclone's "Shared with me" is a special folder, not a permission level
