# Phase 7C-4 PostgreSQL Validation — DEFERRED

Status: **WAITING FOR COMPANY POSTGRESQL VALIDATION**

Do not run against Neon. Execute only after the company-controlled PostgreSQL migration and AUTH05 validation are explicitly authorized.

Required database scenarios:

1. Apply AUTH05 to a disposable copy and confirm `auth_installations` + `auth_sos_credentials` constraints/FKs.
2. Issue a credential for an active local session and installation; verify only digest is stored.
3. Re-issue for the same installation; verify the previous credential becomes revoked atomically.
4. Expire the ordinary access token while keeping the SOS credential valid; `/emergency/silent-sos` must authenticate the subject.
5. Revoke the installation; the SOS credential must immediately fail.
6. Revoke the credential; it must fail while the ordinary bearer path remains unchanged.
7. Cross-user installation binding must fail.
8. Deleted/inactive user must fail even with an otherwise valid SOS credential.
9. Credential must not authorize location update, cancel, resolve, history, Family, or ordinary API endpoints.
10. `/sos/trigger` must accept the limited credential; `/sos/cancel/*` must not.
11. Repeat-SOS path must preserve existing active-event update and recipient fan-out behavior.
12. Concurrent issue/rotate must not leave two usable credentials for one installation after commit.
13. Transaction rollback during rotation must preserve the previously committed credential.
14. Historical sessions with `auth_installation_id IS NULL` remain usable for ordinary auth; credential issuance associates only the requesting installation.

Physical-device checks remain separate: locked screen/app background, SecureStore survival, offline queue, and native background location continuation.
