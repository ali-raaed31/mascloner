---
status: accepted
---

# 0008. Sixty-Day History Retention

We decided to apply the RetentionPolicy automatically once per day and retain terminal SyncRuns for 60 days. When a run expires, MasCloner deletes that SyncRun, its FileEvents, and its associated log file as one retention operation; pending or running SyncRuns are never eligible.

## Consequences

- Retention is based on terminal age rather than a count of runs, so changing Schedule frequency does not unexpectedly collapse the observable history window.
- The first retention pass after migration occurs only after the backup and configuration migration checks have succeeded.
- Retention is not a backup mechanism; off-disk backups and snapshots follow their own lifecycle.
