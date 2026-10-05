# Phase 7C-2 deferred acceptance

WAITING FOR COMPANY POSTGRESQL VALIDATION.
This document is a plan, not a connection harness. No database or migration has
been run for 7C-2. Never substitute Neon. Execution requires separate authorization
after the company migration and validation are complete.

Prerequisites: review/apply the existing AUTH05 foundation only after validating
AUTH03/04 runtime-created tables. Preserve all users/sessions and existing OTP,
reset and registration-ticket structures. There is no additional 7C-2 migration.
Use synthetic users and an isolated company-authorized disposable database.
Stub delivery/providers; no real SMS, FCM, email or payment calls.

| Case | Required real engine evidence |
|---|---|
| Concurrent first phone access | Unique phone digest insert + row lock serialize across sessions/processes |
| Fifth failure | Four wrong attempts, then concurrent fifth/sixth; durable 900-second lock remains after request error/rollback and challenge deletion |
| Resend versus lock | Issue/resend/verify through login, signup and all SMS-2FA purposes; none reset or evade phone lock |
| Lock expiry | At 899/900 seconds verify boundary; no active-lock extension/reset; new window begins only after expiry |
| OTP expiry | Reject at 300 seconds, including old 600-second rows and requests delayed waiting on the phone lock; verify actual clock_timestamp/transaction behavior |
| Concurrent OTP success | Same code has one successful consumption; only winning transaction creates auth session/tokens |
| Failure ordering | Invalid code commits accounting before HTTP exception; simulated session failure after valid code rolls back consumption and session creation together |
| Registration proof | One proof cannot create two accounts; mismatched phone/purpose rejects; consumed with successful user insert, restored on failed insert |
| Duplicate registration | Same normalized phone with different emails; same case-insensitive email with different phones; validate row/advisory locks and IDs preserved |
| Provider admission race | Google/local/Cognito registration contention; only admitted adult persists; mapped provider IDs keep existing local IDs |
| Provider partial success | Cognito succeeds upstream but local persistence fails; document recovery through mapped/provider login or completing admission, without duplicate local users |
| Existing identity recovery | Local, Google and Cognito users with historical null DOB/phone retain original non-phone login routes; ambiguous phone-login match fails closed |
| Parental invitation | Invalid/revoked invite rolls back proof; canonical parental/minor checks still decide admission; independent minor never persists |
| SQL compatibility | AUTH04 max-age parameter typing, advisory bigint, full-phone CASE, nullable historical phones and all transaction isolation assumptions on target PostgreSQL |
| Session compatibility | Successful phone OTP returns existing JWT/refresh/session format; refresh rotation and native synchronization regressions in their later authorized suites |

Shared Redis validation is ALSO deferred: it is not PostgreSQL proof and needs
separate local/shared infrastructure authorization. Test Lua quotas atomically
across workers, phone and IP limits, purpose switching, fixed-window expiry,
supplemental phone quota without duplicate IP charging, and Redis outage recovery.
Redis outage must return bounded 503/Retry-After 30 on OTP boundaries; it must not
change general API/SOS fallback or erase a durable PostgreSQL phone lock.
Validate minimum secret-key configuration without exposing it. Existing JWT
secret is reused as HMAC input; rotating it changes identity digests and requires
a deliberate compatibility plan in the later session/key rollout, not this slice.

Deployment-specific proxy trust, SMS delivery, provider integration and mobile
authentication UI/device behavior remain outside these offline tests.
