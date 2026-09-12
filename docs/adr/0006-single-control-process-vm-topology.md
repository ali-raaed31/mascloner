---
status: accepted
---

# 0006. Single-Control-Process VM Topology

We decided to support one Google Compute Engine VM running exactly one MasCloner API control process, one in-process scheduler, one active SyncRun, and one SQLite database on local Persistent Disk or Hyperdisk storage. The Streamlit UI remains a separate client process, but additional API workers, schedulers, VMs, and network-mounted SQLite storage are outside the supported topology.

## Consequences

- Process-local scheduling, configuration leases, active-run state, and cancellation are valid only while the one-control-process invariant holds.
- SQLite transactions remain short, use an explicit busy-handling and durability policy, and do not span rclone execution.
- Scaling the API to multiple workers or VMs first requires a dedicated scheduler plus cross-process leadership, configuration coordination, and SyncRun exclusion.
- The disk auto-delete policy is verified deliberately, recoverable backups are stored off the source disk, and restore tests cover SQLite, `.env`, and `rclone.conf`.
