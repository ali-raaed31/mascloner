---
status: accepted
---

# 0005. Separate Execution, Inspection, and Configuration Modules

We decided to replace the monolithic `RcloneRunner` with three deep modules. `SyncExecutor` executes a SyncRun and owns active subprocess supervision, ActiveRunSnapshot production, log parsing, and abort handling; `EndpointInspector` tests endpoint drafts and browses endpoint folders without persisting configuration; and the configuration module owns the storage, validation, migration, redaction, and serialized mutation rules established by ADR-0001 and ADR-0003.

## Consequences

- Endpoint inspection uses temporary rclone configuration and cannot alter the last known-good remotes.
- The scheduler triggers SyncRuns through the SyncExecutor interface rather than managing rclone subprocess details.
- The rclone subprocess seam is internal to these modules and has production and test adapters; it is not exposed as a generic cloud-provider interface.
- Tests exercise each module through its interface, allowing the duplicated synchronous/asynchronous methods and tests of internal helpers to be retired.
