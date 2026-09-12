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
