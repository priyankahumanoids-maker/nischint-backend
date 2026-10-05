# WAITING FOR COMPANY POSTGRESQL VALIDATION

This is a deferred test plan, not an executable test or permission to connect.
After company migration/validation and separate authorization, use an isolated
disposable PostgreSQL fixture with synthetic data, never a discovered URL.

1. AUTH-03/04 baseline plus existing SMS settings: apply AUTH-05; preserve every
   user/session/challenge/reset/refresh/push row and existing indexes/constraints.
2. Same baseline without lazy SMS settings: create its compatible base shape.
   Missing required tables/columns and pre-existing AUTH-05 objects must abort
   before DDL; incompatible types/FKs must fail and roll back, not be replaced.
3. Validate new PK/FK/CHECK/index definitions, nullable legacy extensions, and
   complete transaction rollback on invalid historical prerequisites.
4. Two independent transactions creating the same phone lock row: one PK row;
   five interleaved failures produce a durable 900-second lock without lost
   updates. Resend/purpose change/challenge expiry cannot remove that lock.
5. Concurrent successful OTP/proof use: one consumption/action/audit commit;
   action rollback restores the proof. Denial paths commit failure accounting.
6. Concurrent proof consumption versus session revocation/logout-all: no usable
   action after revocation takes effect. Recheck current Family authority.
7. Existing refresh replay/simultaneous refresh/logout-all tests remain intact.
8. Concurrent first/same/new-installation registration: deterministic notice
   state, one user/identity row; same installation on another account isolated.
9. Legacy FCM token ownership transfer succeeds even after metadata association;
   stale association cannot select the new owner's token for the prior user.
10. Expired ordinary session cleanup leaves SOS credential and installation
    records intact. Revoked installation/credential and wrong scope denied.
11. Phone-change partial unique index denies two pending operations per user;
    recovery delay/terminal checks enforce 24-hour and completion consistency.
12. Two concurrent valid TOTP uses of one timestep: one accepted; ciphertext
    stays encrypted and SMS preferences unchanged. Enrollment/recovery require
    later authenticated step-up and real encryption/TOTP adapters.

Do not substitute SQLite/fake sessions for PostgreSQL lock/uniqueness proof.
Run full native/mobile/provider acceptance only in their separately authorized
later slices; no 7C-1 test plan grants that authorization.
