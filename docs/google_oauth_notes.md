Google Drive OAuth notes

- Use rclone authorize to obtain the token from a machine with a browser.
- If you have your own Google OAuth client, create a Desktop app client ID/secret and save them via the UI. They are stored encrypted in .env.
- When running rclone authorize on another machine, either pass client_id and client_secret directly to rclone authorize, or set RCLONE_DRIVE_CLIENT_ID and RCLONE_DRIVE_CLIENT_SECRET in the environment on that machine first.
- The token JSON should ideally include refresh_token to allow automatic refresh. If it is missing, Google may expire access soon; re-authorize and consider publishing your OAuth app or using internal mode for Workspace to get offline access.
- rclone.conf permissions should be 0600. The API now enforces that.
- Scope in rclone is read from the actual rclone config. The UI shows the detected scope from rclone config dump.
- We avoid printing client secret anywhere in the UI.

References
- rclone authorize docs: https://rclone.org/commands/rclone_authorize/
- rclone Google Drive backend: https://rclone.org/drive/