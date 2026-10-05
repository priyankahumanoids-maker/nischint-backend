# Phase 7C-3 PostgreSQL Validation — Deferred

**Status: WAITING FOR COMPANY POSTGRESQL VALIDATION**

Do not run against Neon. Run only after the company-controlled PostgreSQL clone is validated and database execution is separately authorized.

Required real-PostgreSQL checks:

1. Two simultaneous uses of the same local refresh token: exactly one `auth_refresh_consumptions.token_id` insert wins and only one successor is returned.
2. Replay after successful rotation is rejected.
3. `logout-all` starting first holds the users-row auth boundary; a concurrent refresh waits, then fails epoch/session validation after logout-all commits.
4. Refresh starting first holds the users-row auth boundary; logout-all waits, then revokes that session/epoch after refresh commits. No credential remains usable after logout-all completes.
5. Password reset versus refresh follows the same serialization invariant as logout-all.
6. Selected-session revoke versus refresh: either refresh finishes first and the session is then revoked, or revoke wins and refresh fails; no durable post-revocation successor remains usable.
7. Legacy no-`sid` refresh cannot create a new durable session after a completed logout-all/password-reset epoch bump.
8. `auth_user_token_epochs.tokens_valid_after` rejects older local access/refresh credentials after global revocation.
9. `auth_refresh_consumptions` uniqueness and rollback semantics are verified with two real connections.
10. Failed commit after refresh consumption does not return a replacement token; retry semantics are understood.
11. Session active-cache invalidation/revoked-cache behavior matches committed DB state, including rollback/failure handling.
12. Historical `auth_sessions.installation_id IS NULL` sessions remain valid where otherwise authorized.
13. 30-day refresh/session expiry boundary is enforced.
14. Cognito/provider refresh behavior is validated separately as LEGACY PROVIDER REFRESH; do not claim local one-use rotation for provider tokens.

No physical-device test is required to prove these database transaction invariants. 7C-4/7C-9 handle SOS/device/provider acceptance.
