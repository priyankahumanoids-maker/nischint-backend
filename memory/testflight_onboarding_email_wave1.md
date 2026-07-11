# TestFlight Wave 1 — Beta tester onboarding email

> **Use this template for each tester.** Replace the **{{role-specific section}}**
> with the matching role block below. Send a separate email per tester so each
> person sees their own credentials inline (don't bcc — that defeats the point
> of role-targeted testing).

---

## Send-as

- **From:** `meta@nischint.care` (or your real address)
- **Subject:** You're on the Nischint iOS beta — quick setup (10–30 min)
- **Reply-To:** keep this an active inbox; testers reply with feedback

---

## Email body

> Hi {first name},
>
> You're in the first wave of Nischint's iOS TestFlight beta. Thank you — your
> feedback decides what we ship on day 1.
>
> **Setup (3 minutes):**
>
> 1. Install **TestFlight** from the App Store if you haven't already.
> 2. Open the invite I sent through TestFlight (it's a separate Apple
>    email with the subject "Nischint invited you to test"). Tap **Accept**.
> 3. Inside TestFlight, tap **Install** next to Nischint.
> 4. Open the app and sign in:
>
>    > **Email:** `{{account-email}}`
>    > **Password:** `{{account-password}}`
>
>    These credentials are tied to your test role — please don't share them
>    or use them on the web app while testing, or our data will get confused.
>
> **Your test brief ({{role-time-estimate}}):**
>
> {{role-specific-section}}
>
> **Full test plan** (with screenshots later if needed):
> attached as PDF, also at `https://nischint.care/internal/testflight-wave1`
> (login with these same credentials).
>
> **How to send feedback:**
>
> - **Bug or crash:** use TestFlight's built-in feedback (tap the app icon
>   in TestFlight → "Send Beta Feedback"). Crashes auto-attach a stack trace.
> - **Quick "all green":** just reply to this email with `✅ All sections
>   green` and which sections you completed.
> - **Anything else:** reply to this email.
>
> **A few honest notes before you start:**
>
> - This is a real beta, not a polished demo. You'll see slow screens
>   (the Command Center takes ~10s on first load — that's a known
>   improvement queued for Wave 2).
> - One known production issue: `/api/auth/login` may occasionally return
>   a 500 if our cache layer flickers. It auto-recovers in 5 seconds, so
>   just retry. We have a fix in flight to make this fully graceful.
> - We do **not** sell, share, or train anything on your test data.
>   Test accounts are sandboxed; you can delete the data at any time
>   via the Privacy screen inside the app.
> - The build expires in 90 days (Apple's rule, not ours). If you come
>   back later, re-install from TestFlight and you'll get the latest.
>
> **Timeline:**
>
> - Wave 1 window: today through **{{end-date — set to today + 3 days}}**.
> - I'll consolidate your feedback by end of day {{end-date + 1}}.
> - If any showstopper bug is filed, I'll push a Wave 1b build the same day.
> - If all four of you sign off green, we open Wave 2 (external beta —
>   ~20 testers) the following week.
>
> If TestFlight doesn't let you install, or you hit any "can't sign in"
> moment that blocks you from even starting — text me directly on
> WhatsApp at **{{phone}}** so we can unblock you in real time.
>
> Thank you again — you're literally the first humans to put this build
> in real hands.
>
> — Meta
> Nischint
> [https://nischint.care](https://nischint.care) · [https://nischint.care/status](https://nischint.care/status)

---

## Role-specific section — paste into the `{{role-specific-section}}` slot above

### A. For `kidnischint@gmail.com` (role: child)

> You're testing as a **child being monitored by a parent**. Total time: ~10
> minutes.
>
> Walk through these in order:
>
> 1. **Permissions** — when iOS asks for Location, Notifications, and
>    Health, please **read each prompt's wording** before tapping Allow.
>    If any sounds like generic Apple copy ("This app would like to
>    access…") rather than something specific Nischint-authored, that's
>    a bug to file.
> 2. **SOS** — long-press the big red button for 3 seconds. You should
>    feel a haptic and see a full-screen red confirmation in ≤ 2 seconds.
> 3. **Health Data** — go through any HealthKit consent prompts; we read
>    your HR + SpO₂ + step count (read-only — we never write to Apple
>    Health). Then walk around for 30 seconds with the app foregrounded.
> 4. **Privacy & My Data** — find this link near the bottom of your home
>    screen. Tap "Download my data (JSON)" → iOS Share Sheet → Save to
>    Files. Confirm the file opens and contains your profile.
> 5. **Background ride-along** — lock the phone, walk one block, unlock.
>    The app should not have crashed.
>
> When kidnischint is done with steps 2 and 5, the mother tester
> (`mothernischint@gmail.com`) needs to verify she received the SOS and
> can see the route — so coordinate timing if you can.

### B. For `mothernischint@gmail.com` (role: guardian)

> You're testing as a **parent watching a dependent kid (kidnischint)**.
> Total time: ~10 minutes.
>
> 1. **Home** — confirm you see a dependent card for kidnischint.
> 2. **Vitals** — tap the dependent card → tap the VitalsStrip (HR / SpO₂
>    pill) → lands on the **7-day Health History** chart. Toggle between
>    7d and 24h — should be instant. Look for red anomaly dots on the
>    chart.
> 3. **SOS receipt** — coordinate with kidnischint so they trigger an
>    SOS while you're in the app. You should get a push notification in
>    ≤ 5 seconds. Tap it; an alert detail with kidnischint's last
>    location should appear.
> 4. **Privacy & My Data** — Profile tab → "Privacy & My Data". Download
>    the JSON; verify it includes data for the dependents you guard
>    (scope-correct).
>
> The big things we want to know: did the SOS push arrive fast?
> Did the chart render quickly? Did anything else feel slow?

### C. For `nischint4parents@gmail.com` (role: admin / guardian)

> You have admin privileges. Total time: ~10 minutes.
>
> 1. **Guardian basics** — repeat sections 1 and 2 from the guardian
>    brief above (you have those powers too).
> 2. **Command Center** — open `https://nischint.care/command-center` in
>    mobile Safari (sign in with the same credentials). You should see
>    the Risk Panel + Incident Feed + a Map.
> 3. **Trust Confidence Chip (OCE-01)** — tap any incident in the Risk
>    Panel. A blue/amber/green chip should appear below the panel with
>    a score ring, trend pill ("Improving" / "Stable" / "Degrading"),
>    and a 7-day sparkline. Tap the chevron to expand the explanation —
>    you should see 3–5 plain English lines.
> 4. **Public status page** — open `https://nischint.care/status`
>    (no login needed). Confirm all 4 components show "Operational" or
>    something honestly-degraded. Note the uptime %.
> 5. **Admin Privacy** — confirm your admin-account data download is
>    scope-correct (your own admin profile only — not a dump of every
>    user's data).
>
> Admin-specific bugs to watch for:
> - Does the Trust chip show real history (sparkline with > 0 points)
>   or "No history yet"? Either is fine, but if it's been more than
>   24 hours since deploy and still "No history yet" let me know — that
>   means the nightly scheduler didn't run.

### D. For `womennischint@nischint.com` (role: woman)

> You're testing as a **solo user** — no guardian, no dependents — using
> Nischint's women-safety mode. Total time: ~10 minutes.
>
> 1. **Home** — confirm you see the solo-mode home: a Journey CTA, an
>    SOS button, and an "Add Trusted Contact" prompt if no contact is set.
> 2. **Add trusted contact** — pick any name from your phone's address
>    book. Confirmation should appear.
> 3. **Start a Journey** — enter any destination you're walking/driving to.
>    Map should render with a route line. Banner should read "Sharing
>    live with {contact name}".
> 4. **SOS during journey** — while the journey is active, long-press
>    SOS for 3 seconds. Distress should fire to both Nischint server
>    AND your trusted contact in ≤ 2 seconds.
> 5. **Voice distress** *(if your build has this enabled)* — say
>    "Help me!" loudly while the app is foregrounded. Same distress
>    behaviour should fire within ~4 seconds.
> 6. **Arrive safely** — tap "I've arrived safely". Banner should
>    disappear and your trusted contact should get a confirmation.
> 7. **Privacy & My Data** — confirm the trusted contact you added shows
>    up in the JSON download.
>
> The big things we want to know: did the trusted contact actually get
> the alerts you triggered? How fast? Did the route share work the
> entire walk/drive?

---

## After all 4 testers report back

If 3 or 4 of 4 are green → schedule Wave 2 (external beta, ~20 testers via
TestFlight public link). Confirmed showstopper bug pattern: any "crash on
launch" report from a tester, OR any "no SOS arrived" report. Anything
else is a Wave 2 fix, not a Wave 1 blocker.
