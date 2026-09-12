---
status: accepted
---

# 0004. Dedicated Google Drive to Nextcloud Architecture Scope

We decided to keep MasCloner explicitly purpose-built for synchronizing one GoogleDriveSource to one NextcloudDestination rather than designing a multi-cloud abstraction layer. The managed rclone remote names are fixed internal identifiers, `gdrive` and `ncwebdav`; users configure the two domain endpoints rather than arbitrary remote names or providers. Tailoring the domain terminology, setup flow, command construction, and error handling to Google Drive and Nextcloud WebDAV maximizes module depth and maintainer locality.

## Consequences

Generic provider interfaces, configurable remote names, and arbitrary remote-management endpoints are out of scope. An existing installation using other remote names is normalized during the validated configuration migration and is not switched until a dry-run succeeds.
