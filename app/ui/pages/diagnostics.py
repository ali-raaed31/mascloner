"""System Diagnostics and Preflight health check view for MasCloner console."""

from __future__ import annotations

from datetime import datetime, timezone
import json
import time
from typing import Any, Dict, List, Optional
import streamlit as st

try:
    from app.ui.api_client import APIClient
    from app.ui.components.theme import (
        format_bytes,
        format_iso_time,
        render_hero_bar,
    )
except ImportError:
    from api_client import APIClient
    from components.theme import (
        format_bytes,
        format_iso_time,
        render_hero_bar,
    )


def get_api() -> APIClient:
    return APIClient()


api = get_api()

st.title("🩺 System Diagnostics")
render_hero_bar(api)

st.subheader("System Preflight Diagnostics")
st.caption("Perform non-destructive health checks across the API server, database, authentication, and cloud endpoints")


def run_diagnostics() -> Dict[str, Any]:
    """Execute complete suite of diagnostics."""
    report: Dict[str, Any] = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "checks": {},
        "all_passed": True,
    }

    # 1. API Health Check
    t0 = time.perf_counter()
    health = api.get_health()
    api_ms = (time.perf_counter() - t0) * 1000.0
    report["checks"]["api_health"] = {
        "title": "API Backend Health",
        "passed": bool(health and health.get("status") == "healthy"),
        "latency_ms": round(api_ms, 1),
        "details": health or {"error": "Unreachable"},
    }

    # 2. Authentication Boundary Check
    t0 = time.perf_counter()
    auth_ok, auth_msg = api.check_auth()
    auth_ms = (time.perf_counter() - t0) * 1000.0
    report["checks"]["auth_boundary"] = {
        "title": "Authentication Boundary",
        "passed": auth_ok,
        "latency_ms": round(auth_ms, 1),
        "details": {"message": auth_msg},
    }

    # 3. Database Engine & Schema
    t0 = time.perf_counter()
    db_info = api.get_database_info()
    db_ms = (time.perf_counter() - t0) * 1000.0
    report["checks"]["database"] = {
        "title": "SQLite Database & Engine",
        "passed": bool(db_info and "total_runs" in db_info),
        "latency_ms": round(db_ms, 1),
        "details": db_info or {"error": "Database query failed"},
    }

    # 4. Google Drive OAuth Connection
    t0 = time.perf_counter()
    gd_res = api.test_google_drive_connection()
    gd_ms = (time.perf_counter() - t0) * 1000.0
    report["checks"]["google_drive"] = {
        "title": "Google Drive Source (Remote: gdrive)",
        "passed": bool(gd_res and gd_res.get("success")),
        "latency_ms": round(gd_ms, 1),
        "details": gd_res or {"error": "Connection probe failed"},
    }

    # 5. Nextcloud WebDAV Connection
    t0 = time.perf_counter()
    nc_res = api.test_nextcloud()
    nc_ms = (time.perf_counter() - t0) * 1000.0
    report["checks"]["nextcloud"] = {
        "title": "Nextcloud Destination (Remote: ncwebdav)",
        "passed": bool(nc_res and nc_res.get("success")),
        "latency_ms": round(nc_ms, 1),
        "details": nc_res or {"error": "WebDAV probe failed"},
    }

    # 6. Configuration Validation
    t0 = time.perf_counter()
    cfg_val = api.validate_config()
    cfg_ms = (time.perf_counter() - t0) * 1000.0
    report["checks"]["config_validation"] = {
        "title": "Configuration Consistency",
        "passed": bool(cfg_val and cfg_val.get("valid", True)),
        "latency_ms": round(cfg_ms, 1),
        "details": cfg_val or {"error": "Validation failed"},
    }

    report["all_passed"] = all(c["passed"] for c in report["checks"].values())
    return report


# Run or display diagnostics
if "diag_report" not in st.session_state:
    st.session_state.diag_report = None

col_btn, col_down = st.columns([2, 1])

with col_btn:
    if st.button("🩺 Run Full Preflight Diagnostics Suite", type="primary", use_container_width=True):
        with st.spinner("Running diagnostics across all subsystems...", show_time=True):
            st.session_state.diag_report = run_diagnostics()

report = st.session_state.diag_report

if report:
    with col_down:
        json_report = json.dumps(report, indent=2)
        st.download_button(
            label="📥 Download Diagnostic Report (JSON)",
            data=json_report,
            file_name=f"mascloner_diagnostics_{report['timestamp'][:10]}.json",
            mime="application/json",
            use_container_width=True,
            on_click="ignore",
        )

    st.markdown("---")
    
    if report["all_passed"]:
        st.success("🟢 **All System Subsystems Operational & Passed Diagnostics**")
    else:
        st.error("🔴 **One or More Subsystem Diagnostics Reported Warnings or Errors**")

    # Display checks
    for key, check in report["checks"].items():
        icon = "🟢" if check["passed"] else "🔴"
        status_text = "PASS" if check["passed"] else "FAIL"
        
        with st.expander(f"{icon} {check['title']} — {status_text} ({check['latency_ms']} ms)", expanded=not check["passed"]):
            st.json(check["details"])

else:
    st.info("Click **'Run Full Preflight Diagnostics Suite'** above to verify end-to-end operational health.")
