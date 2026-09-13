# MasCloner Operator Guide

This guide details the deployment, storage, durability, and operational maintenance procedures for running MasCloner on Google Cloud Platform.

## 1. VM Topology and Storage Requirements

Per [ADR 0006](file:///home/alirun/projects/cloner/docs/adr/0006-single-control-process-vm-topology.md):
- **Single Control Process**: Exactly one MasCloner control process (FastAPI + APScheduler) runs per deployment VM. Starting a second instance against the same database is prevented by an active PID lease (`run/mascloner.pid`).
- **Persistent Local Block Storage**: The database (`mascloner.db`), configuration directory (`etc/`), and logs (`logs/`) must reside on a VM-attached Persistent Disk or Hyperdisk (e.g. `pd-balanced` or `pd-ssd`) formatted with `ext4` or `xfs`.
- **Prohibited Filesystems**: Network-attached filesystems (such as NFS, CIFS, SMB, GlusterFS, or Ceph) are **strictly prohibited** for the SQLite database. SQLite WAL mode requires POSIX shared-memory primitives and deterministic fsync behavior that network filesystems cannot reliably provide.

### Verifying Disk Attachment & Snapshot Policy
Verify Google Cloud Persistent Disk auto-delete and snapshot schedule via Google Cloud CLI:
```bash
# Verify disk auto-delete is disabled on critical data disks
gcloud compute instances describe <INSTANCE_NAME> \
  --zone=<ZONE> \
  --format="table(disks[].source,disks[].autoDelete)"

# Verify snapshot schedule attachment
gcloud compute disks describe <DISK_NAME> \
  --zone=<ZONE> \
  --format="value(resourcePolicies)"
```

---

## 2. SQLite Durability & Policies

All application database connections automatically apply the following PRAGMAs:
- `PRAGMA journal_mode = WAL`: Write-Ahead Logging allows concurrent readers and writers without lock contention.
- `PRAGMA synchronous = NORMAL`: Guarantees durability across application crashes while minimizing disk sync overhead in WAL mode.
- `PRAGMA foreign_keys = ON`: Enforces relational integrity across all tables (such as `runs` and `file_events`).
- `PRAGMA busy_timeout = 5000`: Allows up to 5000ms for concurrent locks to resolve before raising busy exceptions.

Short transaction boundaries are enforced: no database transaction is held open across external subprocess executions (such as `rclone sync`).

---

## 3. Database Backup Procedure

Live SQLite files (`mascloner.db`, `mascloner.db-wal`, `mascloner.db-shm`) must **never** be copied directly with raw file copy utilities (`cp`, `rsync`, or raw `tar`) while the application is running.

### Online Backup Tooling
MasCloner provides a consistency-checked online backup tool utilizing `sqlite3.Connection.backup()`:

```bash
# Run online backup tool manually:
python3 ops/scripts/backup_db.py --target /var/backups/mascloner/mascloner_manual.db

# Or trigger via API endpoint:
curl -X POST http://127.0.0.1:8787/maintenance/backup
```

The online backup operation:
1. Safely streams pages from the live database without blocking concurrent read/write operations.
2. Applies strict `0600` permissions to the backup artifact.
3. Executes `PRAGMA integrity_check` and `PRAGMA foreign_key_check`.
4. Performs a disposable restore verification query before marking the backup artifact as valid.
5. Deletes partial or corrupted artifacts on failure, leaving the live database untouched.

### Full System Backup
The operational backup script `ops/scripts/backup.sh` archives configuration (`.env`, `etc/`) and triggers `backup_db.py` to create verified database snapshots in `/var/backups/mascloner`.

---

## 4. Disaster Recovery & Restore Procedure

In the event of database corruption or VM recovery:

1. **Stop the MasCloner services**:
   ```bash
   sudo systemctl stop mascloner-api mascloner-ui
   ```

2. **Verify the candidate backup artifact**:
   ```bash
   sqlite3 /var/backups/mascloner/candidate_backup.db "PRAGMA integrity_check;"
   sqlite3 /var/backups/mascloner/candidate_backup.db "SELECT count(*) FROM config;"
   ```

3. **Archive the existing data directory**:
   ```bash
   mv /srv/mascloner/data /srv/mascloner/data.broken.$(date +%s)
   mkdir -p /srv/mascloner/data
   ```

4. **Restore the database**:
   ```bash
   cp /var/backups/mascloner/candidate_backup.db /srv/mascloner/data/mascloner.db
   chmod 0600 /srv/mascloner/data/mascloner.db
   ```

5. **Start the MasCloner services**:
   ```bash
   sudo systemctl start mascloner-api mascloner-ui
   ```

6. **Verify health**:
   ```bash
   curl -s http://127.0.0.1:8787/status | jq .
   ```

---

## 5. History Retention Policy (ADR 0008)

Per [ADR 0008](file:///home/alirun/projects/cloner/docs/adr/0008-sixty-day-history-retention.md):
- **Default Retention**: Terminal `SyncRun` records (`completed`, `failed`, `aborted`, `skipped`) are retained for **60 days**.
- **Active Run Protection**: Runs in `pending` or `running` states are never eligible for deletion regardless of age.
- **Atomic Deletion**: When an expired run is deleted, its dependent `FileEvents` and associated log files (`run.log_path`) are removed as part of the retention operation.
- **Daily Automatic Schedule**: The background scheduler automatically executes the retention pass once per day at 03:00 UTC.

### Operator Prune Command
Operators can simulate or manually trigger history pruning using the CLI:
```bash
# Dry-run mode: verify what would be deleted without modifying database or filesystem
mascloner prune --dry-run

# Run retention manually with custom days override:
mascloner prune --days 60 --batch-size 100
```

### API Endpoints
- **Inspect Policy & Last Report**:
  ```bash
  curl -s http://127.0.0.1:8787/maintenance/retention | jq .
  ```
- **Trigger Retention On-Demand**:
  ```bash
  curl -X POST "http://127.0.0.1:8787/maintenance/retention?dry_run=true"
  curl -X POST "http://127.0.0.1:8787/maintenance/retention?dry_run=false"
  ```

---

## 6. Architecture Migration & Rollback (v3.0.0 Cutover Runbook)

Per [ADR 0001](file:///home/alirun/projects/cloner/docs/adr/0001-explicit-configuration-ownership.md) and [ADR 0003](file:///home/alirun/projects/cloner/docs/adr/0003-managed-rclone-configuration.md), migrating from legacy versions to v3.0.0 enforces a backup-first, zero-guesswork cutover workflow.

### Prerequisites
1. **VM Topology**: Single control process on VM with local block storage.
2. **Free Disk Space**: At least 100MB (or 2.5x current database size) free in `/var/backups/mascloner`.
3. **Database Integrity**: Live SQLite database must pass `PRAGMA integrity_check`.

### Downtime Expectation
- **Maintenance Window**: 30–60 seconds total.
- The service is quiesced, active executions reconciled, backup bundle verified, and new configurations promoted atomically before restarting the control process.

### Step-by-Step Procedure

1. **Preflight Health Inspection**:
   ```bash
   mascloner migrate --check
   ```
   Validates filesystem topology, storage free space, write permissions, database integrity, and verifies no active runs are holding uncommitted state.

2. **Simulate Cutover (Dry-Run)**:
   ```bash
   mascloner migrate --dry-run
   ```
   Inventories legacy `.env`, SQLite `ConfigKV`, and `rclone.conf` remotes. Calculates proposed v3 mappings and proves zero persistent disk or database mutations.

3. **Apply Cutover**:
   ```bash
   mascloner migrate --apply
   ```
   The apply procedure performs the following atomic sequence:
   - Quiesces the service and reconciles any stale non-terminal runs.
   - Creates a verified, timestamped recovery bundle in `/var/backups/mascloner/migration_recovery_bundle_<timestamp>/`.
   - Migrates legacy run statuses (`success`, `error`, `stopped`, `partial`) to canonical statuses.
   - Imports mutable schedule (`enabled=true`), sync folder paths, performance parameters, and retention settings into SQLite.
   - Validates and establishes fixed `gdrive` and `ncwebdav` remotes in managed `rclone.conf`.
   - Records cutover version (`3.0.0`) and enables daily history retention.

4. **Post-Cutover Smoke Verification**:
   ```bash
   # Check service and database health
   mascloner status
   
   # Verify schedule continuity
   curl -s http://127.0.0.1:8787/schedule | jq .
   
   # Validate fixed remotes
   curl -s http://127.0.0.1:8787/oauth/google-drive/status | jq .
   curl -s http://127.0.0.1:8787/test/nextcloud/status | jq .
   ```

### Emergency Rollback Procedure
If any unexpected failure or behavioral regression occurs post-cutover:
```bash
mascloner migrate --rollback /var/backups/mascloner/migration_recovery_bundle_<timestamp>
```
The rollback procedure:
- Stops active processes and disposes database locks.
- Restores `mascloner.db`, removing any stray WAL/SHM files.
- Restores original `.env` and `rclone.conf`.
- Verifies restored SQLite database integrity before completing.
