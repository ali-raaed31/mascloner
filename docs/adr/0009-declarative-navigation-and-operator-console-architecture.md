---
status: accepted
---

# 0009. Declarative Navigation and Operator Console Architecture

We decided to restructure the frontend user interface for MasCloner v3.1.0 using Streamlit 1.38's declarative `st.navigation` and `st.Page` architecture, organizing the interface into three semantic operator sections (`Operations`, `Configuration`, `System`) while centralizing authentication at the entrypoint router.

We decided to replace the fragmented, multi-step consumer onboarding wizard and heavy folder-tree picker with an operational **SyncRoute** verification card that presents the active `GoogleDriveSource` and `NextcloudDestination` status, paths, and health indicators directly, while placing manual path modifications into a collapsed advanced drawer.

We decided to retain a dedicated **Live Monitor** page for detailed real-time run telemetry and streaming logs, decoupled from the high-level **Dashboard**, utilizing non-blocking `@st.fragment(run_every="2s")` partial rendering rather than full-page blocking sleeps.

## Consequences

- Streamlit's default filesystem-based numbered page routing (`2_Settings.py`, `3_Runs_and_Events.py`, etc.) is eliminated, resolving sidebar gaps and fragmented page ordering.
- Authentication (`require_auth`) is enforced globally in `Home.py` before running the navigation router, ensuring unauthenticated requests cannot bypass security by loading subpages directly.
- The user interface is aligned with the realities of an internal tool operated by two engineers: high-signal glanceability, instant endpoint verification, and zero blocking execution loops.
- Folder selection widgets no longer dominate the primary navigation; path configuration changes are treated as infrequent administrative actions.
- Real-time log streaming and progress monitoring operate within isolated component fragments, preserving client responsiveness and preventing UI state flicker.
