# Configuration Ownership Migration

> Implemented cutover contract. Installations that already contain a
> `migration_version` marker are complete and must use the ordinary update and
> backup workflows; never rerun `mascloner migrate --apply` on them.

This migration moves a running single-VM installation from overlapping environment, database, and rclone configuration to the ownership model in ADR-0001 and ADR-0003 without invalidating working endpoints.

## Ownership after migration

| State | Authority |
|---|---|
| Process paths, bind settings, and host authentication | `.env` |
| Schedule enabled state, interval, jitter, selected folders, rclone performance settings, and retention | SQLite |
| Fixed `gdrive` and `ncwebdav` remotes, endpoint credentials, and OAuth token state | Managed `rclone.conf` |

No field is authoritatively stored in more than one location. The configuration module presents typed, redacted values to callers and hides the storage formats.

## Preconditions

- The API remains a single control process on one VM.
- SQLite and `rclone.conf` are on local Persistent Disk or Hyperdisk storage.
- A consistent SQLite backup and copies of `.env` and `rclone.conf` exist outside the source disk.
- The current Schedule state and most recent successful SyncRun are recorded for comparison.

## Migration sequence

1. Leave the existing `.env`, `MASCLONER_FERNET_KEY`, database, and `rclone.conf` untouched while inspecting them.
2. Resolve each current setting to its new authoritative owner and reject conflicting or invalid values instead of guessing.
3. Validate the existing GoogleDriveSource and NextcloudDestination from temporary rclone configuration.
4. If necessary, copy the validated remotes to the fixed `gdrive` and `ncwebdav` names without deleting the originals.
5. Write the Schedule, selected paths, complete rclone performance settings, and RetentionPolicy to SQLite with `imported_legacy` provenance. Nonempty SQLite and `.env` values must agree; empty paths and invalid values stop the cutover.
6. Run a read-only endpoint inspection followed by an rclone dry-run using the fixed remotes and the migrated SQLite settings.
7. Atomically promote the validated candidate config under the configuration lease, then record the cutover marker only when every validation succeeds.
8. Start the application, verify Schedule state, trigger or observe one SyncRun, and verify OAuth refresh plus Nextcloud access.
9. Preserve legacy environment entries and old remote sections as rollback data. Do not delete them automatically.
10. Enable daily retention only after the migration and backup checks have completed.

## Failure and rollback

Any failure before the switch leaves the current configuration active. A failure after the recovery bundle is made restores SQLite, `.env`, and `rclone.conf` from that verified bundle while services remain stopped. Operators restart services only after the restore verification succeeds.

Legacy Fernet-encrypted values are read only for compatibility during migration. New configuration is not Fernet-encrypted, and removal of the key and legacy values requires a later explicit cleanup after rollback is no longer needed.

## Operator rules

- Configure, reconnect, and remove endpoints through MasCloner.
- Do not run mutating `rclone config`, `config update`, `config reconnect`, or `config delete` commands against the managed configuration.
- Prefer MasCloner endpoint diagnostics over direct rclone commands.
- Never log or expose `rclone config dump` output because it contains credential material.

## Acceptance checks

- An application restart preserves whether the Schedule is enabled or paused.
- A successful no-change execution is recorded as `completed`.
- A rejected overlapping execution is recorded as `skipped`.
- Unexpected restart recovery changes stale `running` SyncRuns to `failed`.
- Deliberate cancellation records `aborted`.
- OAuth refresh does not change SQLite and survives the next settings update.
- A failed endpoint test leaves the previous remote usable.
- Configuration responses never contain credentials or OAuth tokens.
- The first daily retention pass removes only terminal SyncRuns older than 60 days and cascades to their FileEvents and log files.
