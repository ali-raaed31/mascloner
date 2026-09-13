# Architecture Decision Research: Runtime State and Single-VM Deployment

Date: 2026-09-12

## Scope and conclusion

This note checks the external assumptions behind ADRs 0001 and 0003 against the current single-VM deployment in `ops/systemd/mascloner-api.service`, `app/api/main.py`, `app/api/db.py`, `app/api/scheduler.py`, and the rclone configuration code.

**Conclusion:** SQLite as the application-settings authority and an in-process APScheduler are reasonable for the current low-concurrency, single-VM, single-Uvicorn-process deployment. `rclone.conf` cannot be a purely generated artifact when OAuth is used because it contains runtime-mutated token state. ADR-0001 and ADR-0003 therefore assign application settings to SQLite and remote definitions, credentials, and refreshed OAuth state to the managed `rclone.conf`.

## rclone configuration and token refresh

- rclone's official documentation says token-based remotes require a writable config file because rclone updates tokens in it. It also says rclone saves changes through temporary files and renames rather than writing directly. Consequently the **directory**, not only the file, must be writable. The current systemd unit permits writes to `/srv/mascloner/etc`, which is compatible with that behavior. [rclone configuration documentation](https://rclone.org/docs/#configure), [rclone container installation note](https://rclone.org/install/#install-with-docker)
- A Drive token contains access token, refresh token, and expiry data. Token refresh is therefore live credential state, not merely formatting derived from static endpoint settings. [rclone Drive configuration](https://rclone.org/drive/#configuration)
- `rclone config create` and `rclone config update` are mutating interfaces; for OAuth remotes, `config update` refreshes the token by default. A manual `rclone config`, `config reconnect`, `config create`, `config update`, or `config delete` against the managed path can therefore diverge from an authoritative database immediately. [rclone config create](https://rclone.org/commands/rclone_config_create/), [rclone config update](https://rclone.org/commands/rclone_config_update/)
- rclone's atomic rename strategy reduces the chance of a partially written file, but it does not provide an application-level transaction spanning SQLite and the config file. Two independent read-modify-write paths can still produce a last-writer-wins result. The repository already has more than one such path: Python rewrites the Drive section, while Nextcloud setup and removal invoke rclone configuration commands.
- `rclone config dump` can provide a machine-readable view for reconciliation, but its output contains credential material and must not be logged. Password “obscuring” in an rclone config is explicitly not secure encryption, and access tokens are not obscured. A generated `rclone.conf` remains a secret-bearing second copy even if SQLite is authoritative. [rclone config dump](https://rclone.org/commands/rclone_config_dump/), [rclone obscure](https://rclone.org/commands/rclone_obscure/)

### Adopted refinement to ADRs 0001 and 0003

The accepted contract assigns one authoritative owner to every field:

- SQLite owns mutable MasCloner settings: Schedule state, selected paths, performance settings, and retention.
- The managed `rclone.conf` owns the fixed remote definitions, endpoint credentials, and rclone-maintained OAuth token state.
- `.env` owns process bootstrap, filesystem paths, and host authentication. Existing Fernet values remain only for backward-compatible migration and rollback; new configuration is not application-encrypted.

All supported endpoint mutations go through MasCloner. Endpoint drafts are tested using temporary configuration, and the last known-good managed file changes only after validation. Direct mutating rclone configuration commands against the managed path are unsupported and are removed from operator instructions.

This field-level ownership avoids a cross-resource SQLite/filesystem transaction and avoids importing every refreshed token back into SQLite. A process-wide configuration lease serializes supported configuration mutations with SyncExecutor invocations, while rclone remains free to persist refreshed tokens in its own authoritative file.

## SQLite on one VM

- SQLite supports many simultaneous readers but only one simultaneous writer. It is a good fit for device-local storage with low writer concurrency; write-heavy sites or multiple application servers are the point at which a client/server database becomes preferable. MasCloner's current workload—small configuration updates and short run/event commits—fits this envelope if transactions remain short. [SQLite appropriate uses](https://www.sqlite.org/whentouse.html), [SQLite transaction behavior](https://www.sqlite.org/lang_transaction.html#read_transactions_versus_write_transactions)
- The current engine does not select a journal mode, so SQLite's default is rollback-journal `DELETE`. WAL can improve reader/writer concurrency, but still permits only one writer and requires all database users to be on the same host; it is unsuitable on a network filesystem. If WAL is selected, its `-wal` file is part of the persistent state and must stay with the database during raw copies. [SQLite journal modes](https://www.sqlite.org/pragma.html#pragma_journal_mode), [SQLite WAL](https://www.sqlite.org/wal.html)
- Durability should be an explicit policy rather than an assumed default. SQLite documents `WAL + synchronous=FULL` as ACID across power loss; `WAL + NORMAL` remains consistent but may lose the latest committed transaction after power loss. The default rollback-journal `FULL` setting is not necessarily power-loss durable on every filesystem; `EXTRA` adds the directory sync needed for the strongest rollback-mode guarantee. [SQLite synchronous modes](https://www.sqlite.org/pragma.html#pragma_synchronous)
- Configure and test a busy timeout/retry policy for `SQLITE_BUSY`; `check_same_thread=False` only relaxes the Python driver's thread-affinity check and does not remove SQLite's single-writer constraint. [SQLite busy timeout](https://www.sqlite.org/pragma.html#pragma_busy_timeout)
- Repo-specific risk: `sync_job()` retains one SQLAlchemy session across the entire long-running rclone subprocess after refreshing the newly inserted run. Avoid any long-lived read/write transaction there; commit/close before launching rclone and use a fresh short session to finalize the run. This matters more in rollback-journal mode, where locking is less concurrent than WAL.
- For live backups, the SQLite online backup mechanism produces a consistent snapshot while the source remains in use. `ops/scripts/backup.sh` correctly creates a separate `.backup` database, but its earlier tar archive also includes a raw live `data/` copy; only the `.backup` output should be treated as the authoritative database backup unless services are stopped. [SQLite online backup API](https://www.sqlite.org/backup.html)

## APScheduler and process topology

- APScheduler 3.x says an application typically runs one scheduler. Its FAQ states that sharing a job store among worker processes is unsupported because APScheduler has no interprocess synchronization and can duplicate or miss jobs; the documented workaround is a dedicated scheduler process. [APScheduler user guide](https://apscheduler.readthedocs.io/en/3.x/userguide.html#basic-concepts), [APScheduler FAQ](https://apscheduler.readthedocs.io/en/3.x/faq.html#how-do-i-share-a-single-job-store-among-one-or-more-worker-processes)
- The repository uses the default in-memory job store and starts the scheduler from FastAPI lifespan. `max_instances=1` and `_sync_lock = threading.Lock()` constrain only one scheduler/process. If Uvicorn/Gunicorn is ever configured with multiple workers, every worker will create its own schedule and process-local lock, so duplicate syncs become possible. A persistent APScheduler job store would not fix that APScheduler 3.x limitation.
- The current systemd command (`python -m app.api.main`) starts one Uvicorn worker, so the present deployment satisfies the single-scheduler invariant. Record this as an operational constraint and test it. Before adding web workers, move scheduling to a dedicated singleton service or add a separate cross-process leader/lease and cross-process run lock. API endpoints that start, stop, or inspect the scheduler must then address that singleton rather than a random web worker.

## Google Compute Engine storage implications

- “On a VM” does not identify the durability of `/srv/mascloner`. Google distinguishes durable Persistent Disk/Hyperdisk block storage from temporary Local SSD. Local SSD data can be lost on host failure and is discarded on ordinary stop/suspend by default; Google directs non-ephemeral data to Persistent Disk or Hyperdisk. The SQLite database, Fernet key, `rclone.conf`, and backups must not live only on Local SSD. [Compute Engine disk choices](https://cloud.google.com/compute/docs/disks), [Local SSD persistence](https://cloud.google.com/compute/docs/disks/local-ssd#data_persistence)
- Persistent disks are durable independently of a running VM, but deletion behavior is configured per attached disk. If `autoDelete=true`, deleting the VM also deletes that disk; Local SSD is always deleted with the VM. Verify the actual disk backing `/srv/mascloner` and set the intended auto-delete policy rather than assuming a boot disk will survive VM deletion. [Persistent Disk auto-delete setting](https://cloud.google.com/compute/docs/disks/modify-persistent-disk#modifyautodelete)
- Storing `/var/backups/mascloner` on the same disk protects against application mistakes but not disk deletion, operator error, or all zonal failures. Standard snapshots are stored separately from the source disk, survive source-disk deletion, and can be scheduled. Keep an off-disk backup/snapshot and periodically test restoration of the SQLite backup, `.env`/Fernet key, and managed rclone configuration. [Compute Engine snapshots](https://cloud.google.com/compute/docs/disks/snapshots)
- A Persistent Disk mounted through the VM's normal block filesystem satisfies the single-host locality assumed by SQLite. Do not move the database to NFS/SMB/Cloud Storage FUSE merely to make it persistent; SQLite warns about network filesystem locking and WAL requires same-host shared memory. [SQLite over a network](https://www.sqlite.org/useovernet.html)

## Accepted decision checklist

- Assign each configuration field to SQLite, `.env`, or the managed `rclone.conf` as recorded in ADR-0001.
- Put one configuration lease around supported mutations of `rclone.conf` and SyncExecutor invocations; prohibit direct mutating rclone CLI use.
- Keep one API/scheduler process; redesign scheduling and exclusion before enabling multiple web workers or VMs.
- Keep SQLite on a local mounted Persistent Disk/Hyperdisk, use short transactions, configure busy handling, and explicitly choose/test journal and synchronous modes.
- Verify GCE disk type and auto-delete flags; place recoverable backups outside the source disk and test restore.
- Persist Schedule enabled state and canonical SyncStatus values, recover stale runs at startup, and apply 60-day retention daily.
