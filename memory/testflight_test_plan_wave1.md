# TestFlight Beta — Test Plan

> Build target: iOS production profile (`npx eas build --platform ios --profile production`)
> Wave 1 — internal test only. 4 testers, ~3-day window.
> When you're ready, mark each row with ✅ / ⚠ / ✗ in the actual TestFlight feedback thread.

This plan exists so testers know **what to validate, in what order, and what
"done" looks like** — without making them read the source code. Each test is
≤ 5 minutes; total per-tester load is ≤ 30 minutes including install.

---

## 0. Universal pre-flight (all testers)

| # | Step | Expected |
|---|---|---|
| 0.1 | Accept TestFlight invite, install build | Build downloads in ≤ 3 min on Wi-Fi; opens to the splash screen |
| 0.2 | Open the app for the first time | iOS prompts for **Location (always)**, **Notifications**, **HealthKit** in that order. **Each prompt should have a human-readable description** — flag if any look like default Apple copy. |
| 0.3 | Sign in with your account credentials (below) | Lands on the role-correct home screen in ≤ 4s |
| 0.4 | Background → foreground the app twice | No crash, no re-login prompt, no blank screen |
| 0.5 | Send a **TestFlight feedback screenshot** with one sentence "all green" or your first issue | Closes the loop on Wave 1 |

> ⚠ **Crash report rule:** if the app crashes at any point, do NOT skip TestFlight's
> "submit crash report" dialog — just tap "Send". The stack trace lands in
> App Store Connect automatically.

---

## 1. Tester: `kidnischint@gmail.com` — role `child` (~10 min)

You play the dependent — a kid being monitored by a parent.

| # | Test | Path | Expected |
|---|---|---|---|
| 1.1 | **Home renders** | After login | Child-home with a single CTA — "Tap to check in" / SOS button visible |
| 1.2 | **SOS panic** | Long-press the SOS button for 3s | Haptic feedback, full-screen red "SOS sent" confirmation in ≤ 2s |
| 1.3 | **Location share** | Stay on child-home for 30s with the app foregrounded | Background indicator shows location is being shared |
| 1.4 | **Privacy screen** | Tap the small "Privacy & My Data" link near the bottom of child-home | Lands on `/privacy` — DPDP rights list visible, "Download my data (JSON)" + "Download my data (PDF)" buttons present, deletion request button present |
| 1.5 | **Data download — JSON** | Tap "Download my data (JSON)" | iOS Share Sheet appears, save to Files works, JSON contains your profile + last 7 days of health signals |
| 1.6 | **Background tracking** | Lock the phone, walk one block, unlock | No mid-walk crash; route point captured (verify with mother's account later) |

---

## 2. Tester: `mothernischint@gmail.com` — role `guardian` (~10 min)

You're the parent watching kidnischint. Test this AFTER kidnischint has done section 1.

| # | Test | Path | Expected |
|---|---|---|---|
| 2.1 | **Guardian home renders** | After login | Dependent cards visible for kidnischint (and any others in the family) |
| 2.2 | **Vitals strip** | Look at kidnischint's card | HR, SpO₂, last-seen timestamp visible. Numbers may show "—" if HealthKit isn't yet granted on the dependent's device — that's expected, not a bug. |
| 2.3 | **Drill into health history** | Tap kidnischint's VitalsStrip OR the dependent card | Lands on `/health-history?userId=...`. 7-day chart for HR + SpO₂ renders within 2s. |
| 2.4 | **Toggle 7d ↔ 24h** | Tap the segment control at the top of health-history | View switches instantly (client-side filter, no network call) |
| 2.5 | **Anomaly dots** | Look for red dots on the HR chart (HR > 120) or SpO₂ chart (SpO₂ < 94) | If kidnischint has any in the last 7 days, dots are visible. If none, "No anomalies in this window" copy appears below the chart. |
| 2.6 | **SOS alert receipt** | Have kidnischint trigger an SOS (section 1.2) **while you have the app open** | Push notification appears within 5s, tapping it opens an alert detail screen with the dependent's location |
| 2.7 | **Privacy screen access** | Profile tab → "Privacy & My Data" | Same /privacy screen as kidnischint, but with **guardian-scope** controls visible (data of the family you guard, not just yourself) |

---

## 3. Tester: `nischint4parents@gmail.com` — role `admin` (~10 min)

You have operator powers. Test the Command Center surfaces.

| # | Test | Path | Expected |
|---|---|---|---|
| 3.1 | **Admin home** | After login | Same guardian view as mother, **plus** an "Operator Console" / "Command Center" entry |
| 3.2 | **Open Command Center** | Tap the operator console entry **OR** open `https://nischint.care/command-center` in mobile Safari | If on web: see Risk Panel + Incident Feed + Map + Trust Confidence Chip (OCE-01). If on app: see the mobile abbreviated view. |
| 3.3 | **Tap an incident** | Pick any active incident from the Risk Panel | TrustConfidenceChip appears below the panel for that user — score ring + trend pill + 7-day sparkline |
| 3.4 | **Expand chip explanation** | Tap the chevron on the chip | 3–5 plain-English lines appear explaining the score |
| 3.5 | **Public status page** | Open `https://nischint.care/status` in mobile Safari (no login required) | All 4 components show "operational" or honestly-reported state, uptime % visible, recent incidents listed if any |
| 3.6 | **Data export — admin scope** | /privacy screen → "Download my data (JSON)" | JSON contains your admin profile (not all users' data — admin scope is per-self, the multi-user export is a separate flow) |

---

## 4. Tester: `womennischint@nischint.com` — role `woman` (~10 min)

You're a solo user — no guardian, no dependents. Test the women-safety-mode flows.

| # | Test | Path | Expected |
|---|---|---|---|
| 4.1 | **Women-mode home renders** | After login | Solo-mode home — Journey CTA, SOS, "Add a trusted contact" if no contact set |
| 4.2 | **Add a trusted contact** | Tap "Add trusted contact" | Native contacts permission prompt → pick any contact → confirmation shows |
| 4.3 | **Start a journey** | Tap "Start a Journey" → enter a destination | Map renders with route line, "Sharing live with [contact]" banner visible |
| 4.4 | **SOS distress** | While journey is active, long-press SOS for 3s | Distress sent to trusted contact + Nischint server. Confirmation in ≤ 2s. |
| 4.5 | **Voice distress detect** | (If your build has voice trigger enabled) Speak: "Help me!" or your configured trigger phrase, loudly, while app is foregrounded | Same as 4.4 — distress fires within 4s |
| 4.6 | **End journey** | Tap "I've arrived safely" | Journey closes, sharing banner disappears, trusted contact gets a "safe arrival" confirmation |
| 4.7 | **Privacy screen — woman scope** | Profile → "Privacy & My Data" | Same DPDP surface as other roles. Verify the "trusted contact" data is also exportable in the JSON download. |

---

## What to flag — examples

**File a bug if:**
- Any iOS permission prompt shows default Apple text instead of a Nischint-authored description
- App crashes (TestFlight will collect the crash log automatically)
- Any timestamps are off by more than 5 minutes
- Chart shows wrong number range (e.g. SpO₂ > 100)
- "Download my data" produces a file > 10 MB (something's wrong with scope)
- Notifications take > 30s to arrive on the receiving device

**Don't file a bug for** (known and tracked):
- Command Center loading takes ~10s to first render — improvement queued
- Production may show occasional 500s from `/api/auth/login` if Redis is degraded — auto-recovers within ~5s
- "Workers 1" warning in any browser console — platform-level, in flight with support

---

## When you're done

1. Reply to the onboarding email (linked separately) with `✅ Section N — all green` or your bugs filed
2. Build expires after **90 days** by Apple's rule — re-install from TestFlight if you come back later

> Internal questions → ping `meta` in WhatsApp.
> Crash reports → automatic via TestFlight.
> Feature requests → please file in the team Notion (DO NOT email — they get lost).

— Meta · 2026-05-30
