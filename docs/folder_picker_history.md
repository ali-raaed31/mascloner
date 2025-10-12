# Folder Picker Experiment History

This document captures the iterations we went through while trying to build a friendly folder picker for the Sync Paths configuration.

## 1. Modal Tree Explorer (v1)

- Built a modal-based tree explorer rendered from the Setup Wizard.
- Allowed expanding nodes lazily and selecting any depth.
- Issues:
  - Complex recursion and cached state made behaviour hard to reason about.
  - Repeated `experimental_rerun()` calls occasionally caused runaway refresh loops.
  - Performance degraded as the tree grew; rclone queries were chained even when unnecessary.

## 2. Breadcrumb Progressive Picker (v2)

- Replaced the modal with inline progressive dropdowns.
- Breadcrumb displayed the active path and selections were cached per level.
- Added retry logic and manual overrides.
- Issues:
  - Heavy session-state management and fallback logic led to lingering race conditions.
  - Fetching logic was still shared between Google Drive and Nextcloud, so both remotes were queried after each selection.
  - Users observed 5–10 second delays because each dropdown change triggered multiple `browse_folders` calls.

## 3. Tabbed Dual Browser (current approach)

- Abandoned the shared component; now the Sync Paths tab has separate sub-tabs for Google Drive and Nextcloud.
- Each tab:
  - Loads the current path once.
  - Fetches immediate subfolders for the active remote only.
  - Provides “open folder”, “go up”, and manual override buttons without extra caching layers.
- State updates simply adjust local session keys and rerun, eliminating runaway loops.
- Result: simpler logic, faster rclone calls, and clearer UX for editing source/destination paths independently.

## Lessons Learned

- Keep rclone browse operations scoped and minimal—one remote at a time.
- Avoid cross-remote caches; they add complexity and make debugging harder.
- Streamlit reruns should be explicit and rare; most interactions can rely on the natural rerun after user input.
- Manual overrides are still useful, but they should be optional and not compete with auto-fetch logic.
