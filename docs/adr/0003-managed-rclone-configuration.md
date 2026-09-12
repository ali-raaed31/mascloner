---
status: accepted
---

# 0003. Managed rclone Configuration

We decided that the managed `rclone.conf` is the authoritative store for the fixed `gdrive` and `ncwebdav` remote definitions, credentials, and OAuth token state. All application-initiated changes pass through one configuration module; endpoint drafts are validated with temporary configuration before the last known-good managed file is replaced, and the same process-wide lease serializes configuration changes with SyncExecutor invocations so rclone can refresh tokens without a competing writer.

## Consequences

- `rclone.conf` is writable runtime state, not a generated projection of SQLite.
- Endpoint mutation is rejected while a SyncRun holds the configuration lease.
- Direct mutating rclone CLI commands against the managed configuration are unsupported. Users configure and reconnect endpoints through MasCloner; documentation must not instruct them to run `rclone config`, `config update`, `config reconnect`, or `config delete` against the managed file.
- Read-only diagnostic commands do not change ownership, but normal users should prefer MasCloner diagnostics.
- A failed validation or file replacement leaves the last known-good configuration active.
