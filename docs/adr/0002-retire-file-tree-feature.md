---
status: accepted
---

# 0002. Retire In-Memory File Tree Feature

We decided to retire the hierarchical File Tree visualization endpoint and UI page (`/tree` and `5_File_Tree.py`). Reconstructing the tree requires an $O(N)$ scan of retained `FileEvent` history on every page load, so latency and memory grow with event volume even under the 60-day `RetentionPolicy`; maintaining a materialized tree projection would add state and reconciliation complexity that is not justified for a one-way synchronization tool. The ActiveRunSnapshot and per-SyncRun FileEvent history remain the supported administrative views.

## Consequences

The tree route, builder, response models, UI page, tests, navigation entries, and feature documentation are removed together when this decision is implemented. Historical FileEvents remain available until their owning SyncRun expires.
