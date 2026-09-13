# Research & Code Review: Frontend Architecture Revamp for v3.1.0

Date: 2026-09-13  
Branch: `ver-3-1`  
Scope: Streamlit Web UI (`app/ui/`), API Client (`app/ui/api_client.py`), Operator Workflows, and Navigation Architecture

---

## 1. Executive Summary & Context

MasCloner v3.0.0 completed the backend architecture modernization: single configuration ownership in SQLite, lease-protected `rclone.conf`, atomic recovery bundles, 60-day history retention, dedicated Google Drive and Nextcloud endpoints, and lifecycle state management (`SyncRun`, `SyncStatus`, `ActiveRunSnapshot`).

However, the frontend UI remained rooted in legacy v2 patterns. As an internal operational tool used primarily by **two company operators**, the interface currently suffers from:
1. Fragmented navigation with missing/awkward page numbering (`2_Settings.py`, `3_Runs_and_Events.py`, `4_Setup_Wizard.py`, `6_Live_Monitor.py` — pages 1 and 5 are missing).
2. Severe feature and configuration duplication between `2_Settings.py` and `4_Setup_Wizard.py`.
3. Blocking, thread-locking polling patterns (`time.sleep(60)` in history, `time.sleep(2)` loops in live monitor).
4. Incomplete security enforcement: authentication (`require_auth`) is only applied on `Home.py` and `6_Live_Monitor.py`, leaving the other pages unguarded.
5. Critical backend capabilities introduced in v3.0 (60-day retention policies, atomic verified recovery bundle backups, OAuth client credential testing) are completely absent from the UI.
6. Dead code and broken control flow (e.g. unreachable session state assignments following `st.switch_page`, unused helper files like `setup_panels.py`, orphaned `streamlit_app.py`).

This document presents the findings of our research against high-trust primary sources, a two-axis code review (Standards and Spec), and a ground-up design plan for a unified, modern, intuitive operator console for MasCloner v3.1.0.

---

## 2. Primary Sources Investigated

1. **Streamlit 1.38.0 API Capabilities**:
   - `st.navigation` & `st.Page`: Declarative, grouped multi-page navigation eliminating raw filename prefixes and providing clean sidebar grouping.
   - `@st.fragment`: Isolated partial reruns for live polling and progress streaming without locking Python execution threads or causing full-page re-renders.
   - `st.status` & `st.expander`: Container states for clear diagnostic reporting.
2. **Backend API Routers & Contracts** (`app/api/routers/`):
   - `runs.py`: `GET /runs`, `GET /runs/current` (`ActiveRunSnapshot`), `GET /runs/{run_id}/logs`, `POST /runs/{run_id}/stop`, `POST /runs`
   - `schedule.py`: `GET /schedule`, `POST /schedule`, `POST /schedule/start`, `POST /schedule/stop`
   - `config.py`: `GET/POST /config/paths`, `GET/POST /rclone/config`
   - `google_drive.py`: `POST /oauth/google-drive`, `GET/POST /oauth/google-drive/oauth-config`, `POST /oauth/google-drive/oauth-config/test`, `GET /oauth/google-drive/status`, `POST /oauth/google-drive/test`, `DELETE /oauth/google-drive`
   - `nextcloud.py`: `POST /test/nextcloud/webdav`, `POST /test/nextcloud`, `GET /test/nextcloud/status`, `DELETE /test/nextcloud`
   - `maintenance.py`: `GET/POST /maintenance/retention`, `POST /maintenance/backup`, `POST /maintenance/cleanup`, `POST /maintenance/reset`, `GET /database/info`
   - `browse.py`: `GET /browse/folders/{remote_name}`
3. **Domain Vocabulary & Architectural Decisions**:
   - `CONTEXT.md`: Ubiquitous language (`SyncRun`, `SyncStatus`, `ActiveRunSnapshot`, `Schedule`, `FileEvent`, `GoogleDriveSource`, `NextcloudDestination`, `RetentionPolicy`).
   - ADR 0001: Explicit configuration ownership (SQLite owns settings, rclone.conf owns credentials).
   - ADR 0002: Retirement of in-memory File Tree feature (historical events and live run snapshots are authoritative).
   - ADR 0004: Dedicated Google Drive to Nextcloud scope (`gdrive` and `ncwebdav`).
   - ADR 0007: Durable schedule and canonical sync run lifecycle states (`pending`, `running`, `completed`, `failed`, `aborted`, `skipped`).
   - ADR 0008: Sixty-day history retention policy.

---

## 3. Two-Axis Code Review of Current Frontend

### Axis 1: Standards (Code Smells & Quality Gaps)

1. **Duplicated Code (Fowler Smell)**:
   - *System Metrics Display*: Identical 4-metric banner cards (`Scheduler`, `Remotes`, `Config`, `Runs`) are duplicated verbatim in `Home.py`, `2_Settings.py`, and `6_Live_Monitor.py`.
   - *Formatters*: Byte formatting (`MB`, `KB`, `B`) and ISO datetime formatting are re-implemented with differing levels of error handling across 4 different files.
   - *Remote Verification*: Google Drive and Nextcloud testing blocks are implemented twice: once in `2_Settings.py` and again in `4_Setup_Wizard.py` and `components/google_drive_setup.py`.
2. **Dead Code & Speculative Generality**:
   - `app/ui/streamlit_app.py`: 204 lines of orphaned code, never executed by `ops/systemd/mascloner-ui.service` (which executes `Home.py`).
   - `app/ui/components/setup_panels.py`: 120 lines of unimported, unreferenced legacy panel functions.
   - Disjointed page numbering: `2_Settings.py`, `3_Runs_and_Events.py`, `4_Setup_Wizard.py`, `6_Live_Monitor.py` (page 1 is `Home.py`, page 5 was deleted in ADR 0002).
3. **Broken Control Flow**:
   - In `Home.py` (lines 188-192):
     ```python
     with col3:
         if st.button("🔑 Re-auth Google Drive", use_container_width=True):
             st.switch_page("pages/4_Setup_Wizard.py")
             st.session_state.gdrive_reauth = True  # UNREACHABLE! switch_page raises immediate rerun exception
     ```
   - In `3_Runs_and_Events.py` (lines 414-417):
     ```python
     if auto_refresh:
         import time
         time.sleep(60)
         st.rerun()
     ```
     `time.sleep(60)` blocks the worker thread, freezing Streamlit session response.
   - In `6_Live_Monitor.py`: `time.sleep(2); st.rerun()` forces a full-page rerender loop, tearing down DOM state, dropping focus, and causing visual flickering.
4. **Security & Authentication Smells**:
   - Inconsistent authentication guards: Only `Home.py` and `6_Live_Monitor.py` call `require_auth(api)`. When authentication is enabled (`MASCLONER_AUTH_ENABLED=1`), an unauthenticated user can directly access `2_Settings.py`, `3_Runs_and_Events.py`, or `4_Setup_Wizard.py` by clicking them in the sidebar.

### Axis 2: Spec & Domain Conformance

1. **Unexposed Backend Capabilities**:
   - `RetentionPolicy` (ADR 0008): `/maintenance/retention` provides inspection of expired runs, oldest terminal run timestamp, and manual purge execution. The UI has zero visibility or controls for this.
   - Verified Recovery Bundle (ADR 0001, ADR 0006): `POST /maintenance/backup` creates an online atomic SQLite backup with verification hash. The UI only provides "Database Reset (Danger Zone)" and basic cleanup.
   - Custom OAuth Test Endpoint: `POST /oauth/google-drive/oauth-config/test` exists on the backend to test OAuth credentials independently, but `APIClient` has no method for it.
2. **Terminology Drift**:
   - Some UI labels still refer to "Job", "Tasks", "Files Synced by Day", or obsolete remote names.
   - Status indicators do not consistently reflect canonical `SyncStatus` states (`pending`, `running`, `completed`, `failed`, `aborted`, `skipped`).

---

## 4. Operator Needs & UX Rethink (2-Person Internal Operations Team)

For an internal tool run by two engineers/operators:
- They do **not** need a consumer onboarding wizard separate from daily settings.
- They do **not** need to click between 4 different pages to check whether a sync is healthy, what it transferred, and whether the folder path is right.
- They need:
  1. **Immediate Operational Clarity**:
     - Is the scheduler active or paused?
     - Is a sync running right now? What file is it transferring? How fast? Any errors?
     - Can I stop a running sync or trigger a run with a single click?
  2. **Unified Storage & Path Management**:
     - Both endpoints (`GoogleDriveSource` and `NextcloudDestination`) side by side.
     - Interactive folder selection without having to guess rclone folder paths.
     - One-click token renewal and OAuth verification.
  3. **High-Density History & Incident Triaging**:
     - Clean timeline of past `SyncRun`s.
     - Instant filter for failed/aborted runs.
     - Expandable `FileEvent` drilldowns (added, updated, skipped, conflicts, errors).
     - Streaming log viewer that does not refresh the entire browser page.
  4. **System Health & Maintenance**:
     - Engine performance settings (rclone concurrency, pacing, chunks).
     - 60-day retention status and manual purge.
     - Instant verified database recovery bundle generation.

---

## 5. Proposed Ground-Up Frontend Architecture for v3.1.0

### A. Navigation Structure (`st.navigation` & `st.Page`)

Rather than relying on filesystem numbering (`2_...`, `3_...`), the application entry point (`Home.py`) configures structured navigation:

```
MasCloner Console
├── Operations
│   ├── ⚡ Live Dashboard       (Overview, active sync snapshot, live logs, quick triggers)
│   └── 📋 Run History & Audit   (Searchable runs, file event logs, error inspection)
├── Configuration
│   ├── 🔗 Storage & Folders     (Google Drive + Nextcloud setup, auth, interactive folder browsers)
│   └── ⚙️ Schedule & Engine     (Sync interval, jitter preview, rclone concurrency tuning)
└── Maintenance
    ├── 🛡️ Retention & Backups   (60-day policy, verified recovery bundles, DB size)
    └── 🩺 Diagnostics           (Endpoint preflight checks, rclone test logs, API status)
```

### B. Modern Streamlit Technical Standards
- **Global Auth Boundary**: `Home.py` executes `require_auth(api)` before calling `st.navigation().run()`. Every page is automatically and unconditionally protected.
- **Non-blocking Live Streaming**: `@st.fragment(run_every="2s")` on the active run card and log feed, keeping the rest of the application fully responsive without full-page reloads.
- **Shared UI Toolkit**: Single source of truth for formatters (`format_bytes`, `format_duration`, `format_timestamp`), status badges, and consistent alert styles.
- **Elimination of Dead Code**: Complete removal of `streamlit_app.py` and unused legacy components.
