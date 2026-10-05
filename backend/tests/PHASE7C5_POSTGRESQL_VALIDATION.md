# NISCHINT Phase 7C-5 — Deferred PostgreSQL Validation

**Status:** PENDING company-controlled PostgreSQL readiness.  Do not run against Neon and do not change `DATABASE_URL` for this phase.

## Preconditions

1. Company PostgreSQL copy is complete and independently validated.
2. AUTH-05 (`auth05_security_foundation`) has been applied successfully in the approved migration sequence.
3. Phase 7C-1 through 7C-5 source is frozen at the validated local hashes.
4. Testing occurs on an authorized staging/disposable PostgreSQL database before production rollout.

## Required database tests

- **Action proof single use:** one `stepup1.*` proof may authorize exactly one matching user/session/action/circle/target transaction; wrong action, wrong target, wrong session, expiry and replay all fail.
- **Concurrent proof use:** two transactions race on the same proof; exactly one sensitive action commits. A rolled-back action must not burn the proof.
- **Phone change normal path:** old OTP and new OTP are both required; operation digest binding rejects a different number; completion updates the existing user ID without recreating membership/history.
- **Abandoned-operation cancellation:** the authenticated subject can cancel only their own pending operation; cancellation frees the partial unique pending slot and does not alter phone/session/Family/safety state.
- **24-hour recovery boundary:** new-number OTP cannot be requested before `eligible_after`; exactly-at-boundary succeeds after the owner notice is durably queued.
- **Owner notification audience:** recovery for a Circle member writes one idempotent outbox event to `family_circles.owner_user_id`; non-Circle accounts use the explicit `not_required` state.
- **Duplicate phone race:** concurrent completions targeting the same phone serialize on the advisory lock and cannot leave two accounts using the same normalized phone through this workflow.
- **Session invalidation:** successful completion revokes all `auth_sessions`, bumps `auth_user_token_epochs`, revokes `auth_sos_credentials`, deletes old push destinations, and rejects pre-change access/refresh credentials.
- **SMS 2FA continuity:** an enabled SMS 2FA row moves its `phone_hash` to the newly verified number in the same transaction.
- **Legacy guardian removal:** proof consumption and `GuardianRelationship.is_active=False` commit atomically. Rollback retains both the active relationship and usable proof. No `circle_memberships` row is modified.
- **Authority re-check:** when 7C-6 wires canonical lifecycle APIs, current Owner/Co-Admin/member/minor authority must be evaluated at execution time after proof verification; proof possession alone grants no Family permission.

## Concurrency / rollback cases

Use at least two independent PostgreSQL connections for proof-replay and duplicate-phone races. Explicitly force a rollback after proof deletion but before action commit and confirm the proof is still usable afterward.

## Expected result

All tests pass without schema additions beyond AUTH-05. Any required schema change is a stop condition requiring explicit review; do not create or execute an ad-hoc AUTH-06 migration.
