# MasCloner – AI coding agent playbook

Concise, repo-specific guidance to be productive fast. Keep edits small, follow patterns, and verify with local runs.

## Architecture & data flow
- API: FastAPI (`app/api/main.py`) + APScheduler (`app/api/scheduler.py`) + SQLite via SQLAlchemy (`app/api/db.py`, `app/api/models.py`). Schedules/executes rclone, persists `Run`/`FileEvent`/`ConfigKV`.
- UI: Streamlit (`app/ui/Home.py`, `app/ui/pages/*`) talks to the API via `app/ui/api_client.py`.
- Ops/CLI: Typer+Rich CLI (`ops/cli/**`) with legacy bash fallbacks (`ops/scripts/*`); systemd units in `ops/systemd/`.
- Flow: scheduler -> rclone JSON logs -> parse (`app/api/rclone_runner.py`) -> DB -> UI tree (`app/api/tree_builder.py`).

## Develop, run, test
- One-time: `python -m venv .venv && . .venv/bin/activate && pip install -r requirements.txt && python setup_dev_env.py`.
- Run API/UI: `python -m app.api.main` (127.0.0.1:8787) and `streamlit run app/ui/Home.py` (8501).
- Sanity: `python test_db.py`, `python test_rclone.py`.
- CLI: `sudo bash ops/scripts/install-cli.sh` then `sudo mascloner status|update|rollback` (wrapper falls back to legacy scripts).

## Configuration (per .cursor rules)
- Source env via `ConfigManager` (`app/api/config.py`); prefer helpers: `get_base_dir/get_log_dir/get_rclone_conf_path`.
- Prod env lives at `/srv/mascloner/.env` (0600); generate `MASCLONER_FERNET_KEY` during install (never commit). Use `generate_fernet_key()`.
- Validate with `ConfigManager.validate_config()` and `validate_paths()`; keep rclone conf at `${BASE}/etc/rclone.conf`.

## Coding & API patterns
- DB: use `Depends(get_db)` sessions; commit/rollback on errors; models in `app/api/models.py` (indexes defined).
- Endpoints: define Pydantic schemas in `app/api/main.py`; return typed models (`StatusResponse`, `RunResponse`, `FileEventResponse`) or `ApiResponse`.
- Scheduler: use global `SyncScheduler` (`get_scheduler/start_scheduler/stop_scheduler`); single-run lock `_sync_lock` in `sync_job()`.
- rclone: build with `RcloneRunner.build_rclone_command()`; must include `--use-json-log --stats-log-level=NOTICE`. Parser expects official fields `object` + `size`; tests include older `file` field—keep back-compat or update tests.
- Conflicts: prefer `resolve_conflict_filename()`; mark events as `conflict` when applicable.

## Ops & systemd (per deployment rules)
- Services: `mascloner-api`, `mascloner-ui`, `mascloner-tunnel`; hardened units in `ops/systemd/*.service` (env via `/srv/mascloner/.env`).
- Health/backup: use `ops/scripts/health-check.sh` and `ops/scripts/backup.sh`; logs in `${BASE}/logs` with logrotate.
- Updates: modern CLI `mascloner update` manages backup, services, deps; preserves legacy fallbacks (`ops/scripts/mascloner`).

## Verify before commit
- API: GET `/health`, `/status`; trigger `POST /runs`.
- UI: Home metrics load; file tree renders.
- Tests: `python test_db.py` and `python test_rclone.py` pass.
- Ops: `sudo mascloner update --dry-run` shows green steps; services active.

## Style & security (per core rules)
- Python 3.11+, type hints, PEP 8; descriptive names.
- Encrypt secrets with Fernet; never commit real keys; keep secret files 0600; run as `mascloner` user in prod.
