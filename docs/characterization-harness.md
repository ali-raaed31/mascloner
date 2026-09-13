# Characterization Harness

The characterization harness provides completely hermetic, isolated end-to-end integration and characterization tests for MasCloner.

It exercises settings, schedules, Google Drive and Nextcloud endpoints, sync execution, graceful aborts, and legacy database recovery without calling real rclone or any external network/cloud services.

## Running Tests

Run the full characterization suite:

```bash
.venv/bin/pytest tests/characterization/
```

Run specific characterization subsuites:

- **Harness & Fake Rclone Scenarios:**
  ```bash
  .venv/bin/pytest tests/characterization/test_installation_harness.py
  ```

- **Settings, Configuration, & Decryption:**
  ```bash
  .venv/bin/pytest tests/characterization/test_settings_characterization.py
  ```

- **Scheduler Lifecycle & Control:**
  ```bash
  .venv/bin/pytest tests/characterization/test_schedule_characterization.py
  ```

- **Endpoints (OAuth, Nextcloud WebDAV, Browse):**
  ```bash
  .venv/bin/pytest tests/characterization/test_endpoints_characterization.py
  ```

- **Sync Runs, Logs, Events, & Graceful Abort:**
  ```bash
  .venv/bin/pytest tests/characterization/test_runs_and_abort_characterization.py
  ```

- **Legacy Migration & Recovery:**
  ```bash
  .venv/bin/pytest tests/characterization/test_recovery_and_legacy_characterization.py
  ```

## Architecture & Guarantees

1. **Filesystem Isolation (`InstallationRoot`):**
   - Allocates dedicated temporary directories for `etc/`, `data/`, `logs/`, and `bin/`.
   - Never touches `/srv/mascloner`, `~/.config/rclone`, or developer home directory files.

2. **Process State Reset (`ProcessStateReset`):**
   - Intercepts and restores `os.environ`.
   - Rebinds SQLite database engine and session factory to test databases.
   - Clears singletons (`ConfigManager`, `RcloneRunner`, `BackgroundScheduler`).

3. **Fake Rclone Controller (`FakeRcloneController`):**
   - Provides deterministic executable stub on `PATH`.
   - Supports configurable test scenarios: `success`, `non_zero_exit`, `timeout`, `cancellation` (graceful SIGTERM handling), `malformed_output`, and `token_mutation`.
   - Records invocations to JSON for behavioral assertions.

4. **Secret Leak Prevention (`assert_no_secrets_leaked`):**
   - Recursively inspects dictionaries, lists, strings, JSON objects, and files.
   - Asserts that sensitive tokens (Fernet keys, WebDAV passwords, Google OAuth client secrets) never leak into API responses or persisted logs.
