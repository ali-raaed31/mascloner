# MasCloner

Automated one-way synchronization engine and administration system from Google Drive to Nextcloud using rclone.

## Language

### Synchronization & Execution

**SyncRun**:
A single discrete execution of the synchronization process from Google Drive to Nextcloud, tracking lifecycle status, timestamps, transferred volume, and file mutations.
_Avoid_: Job, Task, Process, Batch

**SyncStatus**:
The lifecycle state of a `SyncRun`: `pending` before execution, `running` during execution, `completed` after a successful execution, `failed` after an unsuccessful execution, `aborted` after deliberate interruption, or `skipped` when execution is intentionally not started.
_Avoid_: Success, Error, Stopped, Partial

Legacy stored values are converted only through `app.api.sync_lifecycle.LEGACY_STATUS_MAP`: `success` becomes `completed`; `error` and `partial` become `failed`; `stopped`, `cancelled`, and `canceled` become `aborted`. An unknown legacy value stops the entire conversion before any row changes.

**ActiveRunSnapshot**:
A real-time consolidated summary of the currently executing sync run, providing progress metrics, transfer throughput, and recent file events.
_Avoid_: LiveMonitorData, RunTelemetry, LiveFeed

**Schedule**:
The durable enabled state, timing configuration, and interval trigger rules that govern automated synchronization runs.
_Avoid_: Cron, Job, Cadence

**FileEvent**:
An immutable observation of a file-level outcome during a `SyncRun`, such as a copy, replacement, skip, conflict, or error.
_Avoid_: FileLog, ChangeLog, SyncAudit

### Storage Endpoints & Inspection

**GoogleDriveSource**:
The authenticated Google Drive endpoint and selected folder from which files are read during synchronization.
_Avoid_: GDrive, SourceRemote, Master, Origin

**NextcloudDestination**:
The authenticated Nextcloud WebDAV endpoint and selected folder to which files are copied during synchronization.
_Avoid_: NextcloudWebdav, DestRemote, Replica, Target

**SyncRoute**:
The configured pairing of a `GoogleDriveSource` root folder and a `NextcloudDestination` target folder that defines the permanent synchronization pathway.
_Avoid_: FolderPair, Mapping, SyncPaths, PathConfig

### Configuration & Retention

**RetentionPolicy**:
The rule that retains terminal `SyncRun` history for 60 days, then removes the expired run together with its `FileEvent` history and associated log while never removing an active run.
_Avoid_: PurgeSchedule, DataCleanup, VacuumRules
