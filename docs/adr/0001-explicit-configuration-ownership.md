---
status: accepted
---

# 0001. Explicit Ownership of Runtime Configuration

MasCloner configuration has one authoritative owner per field. SQLite owns mutable application settings, including the `Schedule`, selected source and destination paths, rclone performance settings, and the `RetentionPolicy`; the managed `rclone.conf` owns the fixed `gdrive` and `ncwebdav` remote definitions, credentials, and rclone-maintained OAuth token state; and `.env` owns only process bootstrap, filesystem locations, and host authentication settings. New configuration is not application-encrypted or duplicated across stores: access is protected by the dedicated system user, `0600` file permissions, Google Cloud disk controls, and protected backups.

## Consequences

- Callers use a typed configuration interface; the SQLite key/value representation, environment loading, credential redaction, and rclone file format remain implementation details.
- Application configuration reads must not return credentials or arbitrary contents of `rclone.conf`.
- Existing Fernet-encrypted environment values and `MASCLONER_FERNET_KEY` remain available during the backward-compatible migration, but no new configuration is encrypted with Fernet. They are removed only by a later explicit cleanup after the migrated endpoints have been verified.
- Migration is backup-first and rollback-safe: the existing configuration remains untouched if inspection, normalization to the fixed remote names, endpoint validation, or a dry-run fails.
