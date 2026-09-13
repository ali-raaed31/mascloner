# Google Drive OAuth Notes

- Use rclone authorize to obtain the token from a machine with a browser.
- If you have your own Google OAuth client, create a Desktop app client ID/secret and save them through the MasCloner UI.
- When running rclone authorize on another machine, either pass client_id and client_secret directly to rclone authorize, or set RCLONE_DRIVE_CLIENT_ID and RCLONE_DRIVE_CLIENT_SECRET in the environment on that machine first.
- The token JSON should ideally include refresh_token to allow automatic refresh. If it is missing, Google may expire access soon; re-authorize and consider publishing your OAuth app or using internal mode for Workspace to get offline access.
- The managed `rclone.conf` owns the `gdrive` remote, credentials, and refreshed OAuth token state. Its permissions and containing directory must remain restricted to the MasCloner system user.
- Scope in rclone is read from the actual rclone config. The UI shows the detected scope from rclone config dump.
- We avoid printing client secret anywhere in the UI.
- Do not run mutating rclone configuration commands against MasCloner's managed file. Reconnect, replace, or remove Google Drive through MasCloner so configuration writes cannot race a SyncRun.

Existing installations may retain Fernet-encrypted OAuth client values and `MASCLONER_FERNET_KEY` in `.env` for rollback compatibility. The ownership migration preserves those values but stops creating new encrypted configuration; operators must not delete them until a later explicit cleanup.

See `docs/configuration-migration.md` and ADR-0001/ADR-0003 for the accepted target configuration model. The current release may still use the legacy environment-backed path until that migration is implemented.

## References

- rclone authorize docs: https://rclone.org/commands/rclone_authorize/
- rclone Google Drive backend: https://rclone.org/drive/
