---
status: accepted
---

# 0007. Durable Schedule and SyncRun Lifecycle

We decided that the Schedule is durable SQLite state containing `enabled`, interval, and jitter, and that every accepted or intentionally skipped execution is represented by a SyncRun. SyncStatus is restricted to `pending`, `running`, `completed`, `failed`, `aborted`, and `skipped`: a successful rclone exit is completed even when no files change; a non-successful exit is failed even when some files transferred; a deliberate user or controlled-shutdown interruption is aborted; and an execution intentionally not started because another run is active is skipped.

## Consequences

- Pausing the Schedule survives API and VM restarts.
- Existing installations migrate with `enabled=true` so an update preserves current scheduling behavior.
- Startup recovery changes stale `running` SyncRuns left by an unexpected process or VM failure to `failed`; graceful shutdown records an active SyncRun as `aborted`.
- The former values `success`, `error`, `stopped`, and `partial` are migrated at the storage seam and are not part of the public domain language.
