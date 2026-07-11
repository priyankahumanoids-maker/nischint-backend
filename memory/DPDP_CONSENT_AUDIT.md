# DPDP Consent Audit · Nischint

> Status as of 2026-02 · DPDP-04 sprint
> Owner: Data Protection Officer (privacy@nischint.care)

This document is the source-of-truth audit of every personal-data
category Nischint collects, how (and where) the user grants/revokes
consent, and the gaps remaining for full **DPDP Act 2023 §6** ("notice
and consent") compliance.

## DPDP §6 requirements (the bar we must clear)

Every consent we record must be:

1. **Free, specific, informed, unconditional, and unambiguous.**
2. **Purpose-specific** — one consent per processing purpose, no bundling.
3. **Separately revocable** — toggling one category off must not require
   revoking others.
4. **Stored with an audit trail** — at minimum: who granted, when, from
   which IP / device / app version, and which version of the consent
   text they agreed to.
5. **Withdrawable as easily as it was given** (§6.4).

## Categories we collect

| Category | Identifier | OS permission | DPDP-significance | Required for |
|---|---|---|---|---|
| Location tracking | `location_tracking` | `expo-location` (ALWAYS) | High — sensitive PII, real-time | Live map, SOS, geofence |
| Audio recording | `audio_recording` | `expo-av` recording | High — voice biometric, intimate | Voice distress detection |
| Health vitals | `health_vitals` | `expo-health-connect` / HealthKit | High — health data per DPDP §2(n) | Health-anomaly detection, silent SOS |
| Push notifications | `push_notifications` | `expo-notifications` | Standard | Emergency alerts, SOS callback |
| Biometric sensors | `biometric_sensors` | `expo-sensors` (accelerometer/gyro) | High — biometric per DPDP §2(g) | Fall detection |

## Backend infrastructure (DPDP-04 — shipped)

| Surface | Status |
|---|---|
| `consents` Postgres table (FK CASCADE on user_id) | ✅ |
| `Consent` ORM model with `(user_id, category)` unique constraint | ✅ |
| `GET /api/privacy/consents/me` returning all 5 categories with current state | ✅ |
| `POST /api/privacy/consents/me` upsert grant (idempotent, refreshes `granted_at` + `consent_text_version`) | ✅ |
| `DELETE /api/privacy/consents/me/{category}` revoke (keeps row for audit, sets `revoked_at`) | ✅ |
| Audit fields recorded: `granted_at`, `revoked_at`, `ip_address`, `app_version`, `consent_text_version`, `user_agent` | ✅ |
| Cascade delete on DPDP-01 erasure (consents disappear with the user) | ✅ |
| 400 on unknown category, 404 on revoke-never-granted, 401 on unauthenticated | ✅ |

## Frontend / mobile capture (gaps remaining — P1 follow-up)

The backend can record everything required. **What's missing is the UX
that actually drives DPDP-compliant grants.** Today, our mobile app
uses OS permission prompts (expo-location, expo-av, etc.) without a
preceding purpose-specific consent screen. That's how every app on the
Play Store does it, but it's **not enough for DPDP §6.3** which
requires the data principal to know *what* they're agreeing to before
the OS prompt fires.

### What needs to ship (mobile)

1. **Pre-permission consent sheets.** Before every OS permission prompt,
   show a half-modal sheet with:
   - Purpose-specific copy (use `CATEGORY_METADATA.purpose_en` /
     `purpose_hi` from `app/backend/app/api/consents.py`).
   - "Why we need this" + "What we do NOT do" bullets.
   - Primary action: "Allow & continue" → calls
     `POST /api/privacy/consents/me` with the category, THEN triggers
     the OS prompt.
   - Secondary action: "Skip" → no consent recorded; the corresponding
     feature is disabled.
2. **In-app Privacy Settings screen** (extend `/mobile/app/privacy.tsx`)
   with 5 toggle rows fed by `GET /api/privacy/consents/me`. Toggling
   off calls `DELETE`. Toggling on calls `POST` then re-prompts the OS.
3. **Re-prompt when `consent_text_version` changes.** Bump
   `CURRENT_CONSENT_TEXT_VERSION` in `consents.py` when the copy
   changes; mobile compares server's `consent_text_version` against
   bundled-with-app constant and triggers re-grant.

### What needs to ship (web)

The web SPA does not request OS permissions of any kind today, but the
landing/onboarding flow does present data-collection language. The
acceptance bar is to add a "Manage data consents" link in account
settings that calls the same endpoints, so web users can revoke
consents granted via mobile.

## Compliance verdict (Feb 2026)

| Requirement | Status | Notes |
|---|---|---|
| Purpose-specific consent per category | 🟡 Backend yes, UX no | Backend records per-category but the mobile UI does not capture per-category grants today |
| Separately revocable | ✅ Backend yes, UX in flight | DELETE endpoint works; mobile toggles being built in DPDP-04 follow-up |
| Audit trail | ✅ Yes | All 6 audit fields populated |
| Easy withdrawal | 🟡 Backend yes, UX partial | Today users withdraw via OS settings; in-app revoke screen pending |
| Re-prompt on text change | 🟡 Backend yes, UX no | `consent_text_version` is recorded; client comparison logic pending |
| Self-serve discovery | ✅ Yes | `/api/dpo` and `/api/privacy/consents/me` both live |

**Overall**: DPDP-04 backend layer is **compliant and shipped**. The
mobile UX layer is the remaining gap, tracked as **DPDP-04-MOB** in
ROADMAP. Until DPDP-04-MOB lands, the operational answer to "are we
compliant?" is: yes for users who explicitly use the in-app Privacy
Settings, no for users who only got the OS prompt without a preceding
consent sheet. Recommend prioritising DPDP-04-MOB before any India-
focused marketing push.

## DPO escalation path (DPDP-05 — shipped)

- Page: <https://nischint.care/api/dpo>
- JSON: <https://nischint.care/api/dpo.json>
- Email: privacy@nischint.care
- SLA: 7 days acknowledgement / 30 days substantive response
- Mobile surface: `app/privacy.tsx` → "Data Protection Officer" section
- Web surface: footer link `View full DPO statement` on every page
