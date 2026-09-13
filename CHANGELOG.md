# Changelog

All notable changes to MasCloner are documented in this file.
The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [3.0.0] - 2026-09-13

### Major Architecture & Reliability Release (v3.0.0)

Version 3.0.0 represents a complete architectural modernization and reliability migration for MasCloner. This release establishes single configuration ownership, eliminates process deadlocks and concurrency bugs, introduces atomic backup-first migration, provides 60-day history retention, enforces dedicated Google Drive to Nextcloud endpoints, and replaces the legacy monolithic runner with modular, lease-protected services.

---

### Breaking Changes

1. **Explicit Configuration Ownership ([ADR 0001](file:///home/alirun/projects/cloner/docs/adr/0001-explicit-configuration-ownership.md))**:
   - Runtime configuration (schedule, performance tuning, sync paths, retention policy) is owned strictly by SQLite `ConfigKV`.
   - Host and bootstrap variables (`MASCLONER_DB_PATH`, `MASCLONER_BASE_DIR`, `MASCLONER_AUTH_*`) are owned by `.env` and are immutable after process start.
   - Remote credentials are owned exclusively by `etc/rclone.conf`.
   - Post-cutover fallback reads to `.env` for runtime settings are permanently disabled once the `migration_version` milestone is marked in SQLite.
   - Application-layer Fernet token encryption and storage in `.env` or SQLite is eliminated.

2. **Dedicated Fixed Endpoints ([ADR 0004](file:///home/alirun/projects/cloner/docs/adr/0004-dedicated-gdrive-to-nextcloud-scope.md))**:
   - Endpoints are fixed to Google Drive (`gdrive`) as source and Nextcloud (`ncwebdav`) as destination.
   - Arbitrary remote names in API payloads or CLI flags are rejected with validation errors (HTTP 422).
   - Direct interactive `rclone config` execution scripts (`ops/scripts/oauth/setup-google-drive.sh`) have been removed.

3. **Canonical Run Lifecycle Statuses ([ADR 0007](file:///home/alirun/projects/cloner/docs/adr/0007-durable-schedule-and-sync-run-lifecycle.md))**:
   - The authoritative status state machine consists of: `pending`, `running`, `completed`, `failed`, `aborted`, `skipped`.
   - Legacy statuses (`success`, `error`, `cancelled`, `stopped`) have been retired and are normalized automatically during migration.

4. **Retirement of Recursive File Tree Feature ([ADR 0002](file:///home/alirun/projects/cloner/docs/adr/0002-retire-file-tree-feature.md))**:
   - Full recursive directory tree fetching has been removed in favor of shallow, paged on-demand folder browsing (`EndpointInspector`) to prevent API quota exhaustion and multi-minute request timeouts.

5. **Monolithic `RcloneRunner` Removal ([ADR 0005](file:///home/alirun/projects/cloner/docs/adr/0005-separate-execution-inspection-configuration.md))**:
   - The legacy 1150-line `RcloneRunner` class has been deleted.
   - System responsibilities are cleanly decoupled into:
     - `Configuration`: Type-safe settings models, atomic file updates with process file leases, and SQLite key-value stores.
     - `EndpointInspector`: Non-mutating credential validation, folder browsing, and transfer size estimation.
     - `RcloneCommandBuilder`: Deterministic command synthesis with immutable settings snapshots.
     - `SyncExecutor`: Subprocess management, live JSON event parsing, abort handling, and terminal lifecycle transitions.

---

### New Features & Improvements

- **Backup-First Migration Engine (`app/migration/`)**:
  - `mascloner migrate`: Validates topology preflight, creates a verified recovery bundle containing an online SQLite backup, `.env`, and `rclone.conf` with SHA256 hashes, normalizes legacy rows, and tags the `3.0.0` milestone.
  - `--dry-run`: Complete preflight calculation and mapping simulation with zero persistent side-effects.
  - Emergency rollback: Atomically restores verified backup bundle and purges WAL/SHM artifacts if cutover is aborted.
- **Single Control Process Lease ([ADR 0006](file:///home/alirun/projects/cloner/docs/adr/0006-single-control-process-vm-topology.md))**:
  - `etc/mascloner.lease` tracks the active controller PID and machine ID.
  - Prevents concurrent instances from corrupting local SQLite or executing conflicting rclone tasks.
  - Recovers gracefully from stale leases left by abrupt VM power cycles or crashed processes.
- **Durable Scheduling & Stale Run Recovery ([ADR 0007](file:///home/alirun/projects/cloner/docs/adr/0007-durable-schedule-and-sync-run-lifecycle.md))**:
  - Background scheduler runs within the FastAPI process with configurable jitter to prevent thundering herd API requests.
  - Automatically recovers and transitions interrupted runs (`pending`/`running`) to `failed` upon startup.
  - Skips scheduled runs if a synchronization pass is currently active without blocking the scheduler queue.
- **Automatic 60-Day History Retention ([ADR 0008](file:///home/alirun/projects/cloner/docs/adr/0008-sixty-day-history-retention.md))**:
  - `RetentionService` evaluates runs older than 60 days strictly based on terminal status.
  - Deletes orphaned `FileEvents` and removes associated log files safely.
  - Executes daily at 03:00 UTC and on-demand via `mascloner prune` or `POST /maintenance/retention`.
- **Online Verified SQLite Backups**:
  - `POST /maintenance/backup` and `BackupService` create point-in-time SQLite backups using SQLite's native backup API, verifying database integrity (`PRAGMA integrity_check`) before and after creation.

---

### Operator Rollout & Migration Guide

Refer to [Operator Guide: Section 6](file:///home/alirun/projects/cloner/docs/operator-guide.md#6-v300-architecture-migration-and-cutover-guide) for full cutover and rollback instructions:
```bash
# 1. Stop active services
sudo systemctl stop mascloner-web mascloner-api

# 2. Rehearse migration in dry-run mode
mascloner migrate --dry-run

# 3. Perform verified cutover
mascloner migrate

# 4. Start v3.0.0 service
sudo systemctl start mascloner-api mascloner-web

# 5. Verify system status
mascloner status
```
