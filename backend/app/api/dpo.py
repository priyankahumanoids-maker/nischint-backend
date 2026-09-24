"""DPDP-05: Data Protection Officer (DPO) contact surface.

Serves a static HTML page at `/dpo` (also reachable via `/api/dpo`
through the same router prefix logic — the actual mount point is set
in `api/main.py`).

Per DPDP Act 2023 §10, every Significant Data Fiduciary must designate
a Data Protection Officer and make their contact details discoverable
to data principals. This page is that surface.

The page is plain HTML (no React build dependency) so it loads
instantly, works on every device, and can survive any frontend outage.
"""
from __future__ import annotations

import os

from fastapi import APIRouter
from fastapi.responses import HTMLResponse, JSONResponse

router = APIRouter(tags=["privacy", "dpdp"])

# Bump this when DPO details change.
DPO_NAME = "Nischint Data Protection Officer"
DPO_EMAIL = "privacy@nischint.care"
DPO_RESPONSE_SLA_DAYS = 30

# ── Client legal/content pack received 2026-09-24 ───────────────────
# These are server-side defaults so the mobile app can display the
# client-provided text without duplicating it in the app binary.
# Environment variables still override these defaults after counsel
# approves/publishes a newer version.

CLIENT_LEGAL_VERSION = "2026-09-24"
CLIENT_LEGAL_UPDATED_AT = "2026-09-24"
CLIENT_SUPPORT_EMAIL = "support@nischint.care"

CLIENT_PRIVACY_POLICY = '1.1 Who we are\n\nSkybyte Venture Private Limited, CIN U66190MH2025PTC456397, registered office: [REGISTERED OFFICE ADDRESS — Feroz to confirm before publish]. Contact: connect@skybyteventures.com · +91 74001 79273.\n\n1.2 What NISCHINT does, in plain terms\n\nNISCHINT is an AI-powered urban safety platform for women, children, and senior citizens. It uses location, movement, and (where enabled) voice/audio signals to detect possible distress and route alerts to the user\'s chosen emergency contacts and, where applicable, escalation channels. NISCHINT is a risk-signal and alerting layer — it is not a guaranteed-prevention or emergency-response service, and does not replace police, ambulance, or other emergency services (see Terms & Conditions, Section 2.1, for the full disclaimer).\n\n1.3 Personal data we collect\n\n(a) Data you give us directly\n\n• Account information: name, phone number, email address, password (hashed, never stored in plain text)\n\n• Profile information: age band, relationship role (self / guardian / family member), emergency contact names and numbers\n\n• For a guardian setting up a profile for a child or senior dependant: the dependant\'s name, age, and relationship — collected from and consented to by the guardian, not the dependant, until the dependant is old enough to hold their own account\n\n(b) Data collected automatically through the App\n\n• Location data (GPS/network-based), continuously or on-demand depending on the safety feature enabled by the user\n\n• Movement and behavioral signal data used by NISCHINT\'s detection engine (e.g. sudden stops, deviation from usual routes, geofence exits) — processed to generate a risk signal, never sold or used for advertising\n\n• Voice/audio data, only when the user has explicitly enabled voice-distress detection — processed for distress-pattern detection and not stored as raw audio beyond the window needed to generate that signal, unless an alert is triggered (in which case a short clip may be retained as part of the incident record for the user\'s and responders\' review)\n\n• Device information: device model, OS version, app version, push-notification token, IP address\n\n• Usage data: feature usage, crash logs, session duration — used to improve the App, not to profile individual behavior for any purpose outside safety detection\n\n(c) Data we do not collect\n\n• We do not access your contacts, photos, or messages beyond the emergency contact numbers you explicitly add\n\n• We do not use location or behavioral data for advertising or sell it to any third party, under any circumstance\n\n1.4 Why we process this data (purpose limitation)\n\nEvery category of data above is collected for one or more of these purposes only, consistent with the DPDP Act\'s purpose-limitation principle:\n\n• Providing the core safety service — detecting possible distress and alerting the right people fast\n\n• Account creation, authentication, and customer support\n\n• Legal and safety compliance — retaining an incident record where an alert was actually triggered, for the user\'s own protection and for any subsequent police or family follow-up\n\n• Improving detection accuracy and app reliability (in de-identified/aggregated form wherever possible)\n\n1.5 Consent\n\nLocation, voice/audio, and behavioral-signal processing are enabled through explicit, purpose-specific consent at onboarding and remain toggleable in Settings at any time — see Section 5 of this pack for the exact consent screen copy. Withdrawing consent for a specific signal (e.g. voice detection) turns off that specific feature; it does not delete your account or other data.\n\n1.6 Children\'s data\n\nWhere NISCHINT is used to help protect a child, the child\'s profile is created and consented to by a parent or legal guardian, not by the child. We do not knowingly collect data directly from a child without verifiable parental/guardian consent, we do not use a child\'s data for behavioral advertising or tracking outside the safety purpose stated above, and a guardian may request deletion of a child\'s profile data at any time through the channel in Section 1.9.\n\n1.7 Who we share data with\n\nWe share data only with the service providers who help us run NISCHINT ("data processors"), each bound by contract to use the data solely to provide their service to us, and with emergency contacts/responders you have explicitly designated. Current processors include: cloud hosting and database infrastructure, authentication (AWS Cognito), SMS/voice/WhatsApp alerting (Twilio), transactional email (SendGrid), push notifications (Firebase Cloud Messaging), and content-delivery/security (Cloudflare). Some of these process data on servers located outside India; where that happens, transfer follows the DPDP Act\'s cross-border transfer provisions.\n\nWe do not share personal data with any third party for their own marketing purposes. We may disclose data where legally required — e.g. in response to a lawful request from Indian law enforcement, or where necessary to protect the safety of a user in an active distress event.\n\n1.8 Data retention\n\nAccount and profile data is retained for as long as the account is active. Location and behavioral-signal data used for real-time detection is retained only as long as needed to generate that signal, except where an alert was triggered, in which case the relevant incident record is retained for [RETENTION PERIOD TO BE CONFIRMED — recommend 12 months, aligned with typical safety-incident recordkeeping] to support any follow-up. Data is deleted or anonymized on account closure, subject to any legal retention obligation.\n\n1.9 Your rights under the DPDP Act\n\nAs a Data Principal, you have the right to: access a summary of the personal data we hold about you; correct or update inaccurate data; withdraw consent for any specific processing purpose; request erasure of your data (subject to legal retention requirements); and nominate another individual to exercise these rights on your behalf in case of death or incapacity. To exercise any of these rights, or to raise a grievance, contact our Grievance Officer at [GRIEVANCE OFFICER NAME & EMAIL — to be designated; connect@skybyteventures.com in the interim]. We will respond within the timeline prescribed under the DPDP Act.\n\n1.10 Security\n\nWe use industry-standard technical and organizational measures — encryption in transit and at rest, access controls, and the practices described in our internal Access Control Policy and Incident Response Plan — to protect your data. No system is 100% secure, and we will notify affected users and the relevant authority as required by law in the event of a significant data breach.\n\n1.11 Changes to this policy\n\nWe may update this Privacy Policy from time to time. Material changes will be notified in-app or by email before they take effect.\n\n1.12 Contact us\n\nQuestions about this policy: connect@skybyteventures.com · +91 74001 79273.'

CLIENT_TERMS = 'Effective date: [TO BE SET ON PUBLISH]\n\nThese Terms & Conditions ("Terms") govern your use of NISCHINT, operated by Skybyte Venture Private Limited ("Skybyte", "we"). By creating an account or using the App, you agree to these Terms.\n\n2.1 What NISCHINT is — and is not\n\nNISCHINT is a risk-detection and alerting service. It analyzes location, movement, and (where enabled) audio signals to identify a possible distress situation and to notify the emergency contacts and channels the user has configured, as fast as reasonably possible.\n\nNISCHINT is NOT: a guaranteed-prevention service; a substitute for calling police (100/112), an ambulance (108), or any other official emergency service; a monitored, staffed emergency-response center; or a guarantee that every distress event will be detected, or that every alert will reach its recipient in time. Detection can fail — due to network conditions, device settings, sensor limitations, or the nature of AI-based detection generally. Users must always treat calling official emergency services directly as their primary safety action in any genuine emergency.\n\n2.2 Eligibility and accounts\n\n• You must be at least 18 years old to create your own account. A profile for a minor or a senior dependant may only be created and managed by a parent, legal guardian, or authorized family member on their behalf.\n\n• You are responsible for keeping your login credentials confidential and for all activity under your account.\n\n• You must provide accurate emergency contact information and keep it up to date — alerts are only useful if they reach the right person.\n\n2.3 Subscription, fees, and refunds\n\nNISCHINT may offer both free and paid subscription tiers.\n\n• Paid subscriptions renew automatically for the same term unless cancelled before the renewal date, through the App or the relevant app-store subscription settings.\n\n• Refund Policy: a new paid subscriber may request a full refund within 7 days of first purchase if the Service has not been substantially used (i.e. no safety alert was generated in that window). Beyond 7 days, or for renewal charges, fees are non-refundable except where required by law or by Google Play / Apple App Store policy, whichever store processed the payment.\n\n• We reserve the right to change subscription pricing with at least 30 days\' notice before it applies to existing subscribers.\n\n2.4 Acceptable use\n\nYou agree not to: use the App to harass, stalk, or monitor another person without their knowledge or consent (except a guardian\'s consented monitoring of a minor or a dependant senior, as configured in the App); attempt to reverse-engineer, disrupt, or gain unauthorized access to the App or its infrastructure; or use the App for any unlawful purpose.\n\n2.5 Intellectual property\n\nNISCHINT, the NISCHINT name and logo, and the underlying detection technology (including the Hermes engine and its components) are the intellectual property of Skybyte Venture Private Limited and/or its licensors. Nothing in these Terms grants you any ownership right in the App or its technology.\n\n2.6 Limitation of liability\n\nTo the maximum extent permitted by law, Skybyte\'s total liability arising from your use of the App — including any missed, delayed, or failed detection or alert — is limited to the subscription fees you paid in the 12 months preceding the claim. Skybyte is not liable for indirect, incidental, or consequential damages, including any harm arising from reliance on the App in place of directly contacting emergency services.\n\n2.7 Termination\n\nYou may delete your account at any time from within the App. We may suspend or terminate an account for violation of these Terms, fraudulent activity, or misuse that endangers other users.\n\n2.8 Governing law\n\nThese Terms are governed by the laws of India. Courts in Mumbai, Maharashtra have exclusive jurisdiction over any dispute arising from these Terms.\n\n2.9 Contact us\n\nQuestions about these Terms: connect@skybyteventures.com · +91 74001 79273.'

CLIENT_DPDP_CONSENT = 'NISCHINT only uses what you allow it to. You can change any of these anytime in Settings.\n\n• Toggle 1 — Location: "Allow NISCHINT to use your location to detect unusual movement and to share your location with your emergency contacts during an alert." (Required to use core safety features; declining limits the App to manual SOS only.)\n\n• Toggle 2 — Voice distress detection: "Allow NISCHINT to listen for distress sounds (like a scream) to trigger an automatic alert. Off by default. Audio is analyzed for distress patterns only and is not stored unless an alert is triggered."\n\n• Toggle 3 — Emergency contact sharing: "Allow NISCHINT to share your name, location, and alert details with the emergency contacts you\'ve added, when an alert is triggered." (Required — this is how alerts reach anyone.)\n\n• Toggle 4 — Notifications: "Allow NISCHINT to send you push notifications for safety check-ins, alerts, and account updates."\n\n• Toggle 5 (guardian flow only) — Dependant profile consent: "I confirm I am the parent or legal guardian of [dependant name] and I consent to NISCHINT collecting and processing their location and safety-signal data as described in the Privacy Policy, on their behalf." (Required checkbox, not a toggle — must be affirmatively checked, cannot default to on.)\n\nRead our full Privacy Policy\nRead our Terms & Conditions'

# ── Settings Phase 3A2: remote legal content ─────────────────────────
# Environment values remain authoritative after counsel publishes a
# newer version. Until then, the client-provided 2026-09-24 pack is
# served as the default source for in-app legal/content surfaces.

def _legal_item(
    prefix: str,
    *,
    default_content: str,
    default_url: str | None,
    default_status: str,
) -> dict:
    env_url = (os.getenv(f"{prefix}_URL") or "").strip() or None
    env_content = (os.getenv(f"{prefix}_CONTENT") or "").strip() or None
    env_version = (os.getenv(f"{prefix}_VERSION") or "").strip() or None
    env_updated_at = (os.getenv(f"{prefix}_UPDATED_AT") or "").strip() or None

    content = env_content or default_content
    url = env_url or default_url
    has_env_override = bool(env_url or env_content or env_version or env_updated_at)

    return {
        "status": "published" if has_env_override else default_status,
        "url": url,
        "content": content,
        "version": env_version or CLIENT_LEGAL_VERSION,
        "updated_at": env_updated_at or CLIENT_LEGAL_UPDATED_AT,
    }


@router.get("/public/legal-content", response_class=JSONResponse)
async def public_legal_content():
    """Return the current client-provided legal/content pack.

    Privacy Policy and Terms remain a working draft until counsel publishes
    a final override. DPDP consent copy and support routing are
    implementation-ready per the client's 2026-09-24 content pack.
    """
    return {
        "schema_version": "1",
        "privacy_policy": _legal_item(
            "NISCHINT_PRIVACY_POLICY",
            default_content=CLIENT_PRIVACY_POLICY,
            default_url="https://nischint.care/privacy-policy",
            default_status="draft",
        ),
        "terms": _legal_item(
            "NISCHINT_TERMS",
            default_content=CLIENT_TERMS,
            default_url="https://nischint.care/terms",
            default_status="draft",
        ),
        "dpdp_consent": _legal_item(
            "NISCHINT_DPDP_CONSENT",
            default_content=CLIENT_DPDP_CONSENT,
            default_url=None,
            default_status="published",
        ),
        "support": {
            "email": (os.getenv("NISCHINT_SUPPORT_EMAIL") or CLIENT_SUPPORT_EMAIL).strip(),
        },
    }


@router.get("/dpo.json", response_class=JSONResponse)
async def dpo_contact_json():
    """Machine-readable DPO contact. Used by the mobile Privacy Settings
    screen to render the same info without parsing HTML."""
    return {
        "dpo_name": DPO_NAME,
        "dpo_email": DPO_EMAIL,
        "response_sla_days": DPO_RESPONSE_SLA_DAYS,
        "regulation": "Digital Personal Data Protection Act, 2023 (India), §10",
        "rights_endpoint": "/api/privacy/me",
        "erasure_endpoint": "/api/privacy/me",
        "consents_endpoint": "/api/privacy/consents/me",
    }


@router.get("/dpo", response_class=HTMLResponse)
async def dpo_contact_page():
    """Static HTML page at /api/dpo with DPO contact + DPDP §10 statement."""
    return HTMLResponse(content=_DPO_HTML, status_code=200)


_DPO_HTML = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Data Protection Officer · Nischint</title>
  <meta name="description" content="Nischint's Data Protection Officer contact under the Digital Personal Data Protection Act, 2023.">
  <style>
    :root {{
      --bg: #f8fafc;
      --card: #ffffff;
      --ink: #0f172a;
      --muted: #475569;
      --accent: #4338ca;
      --line: #e2e8f0;
    }}
    @media (prefers-color-scheme: dark) {{
      :root {{ --bg:#0b1220; --card:#0f172a; --ink:#e2e8f0; --muted:#94a3b8; --accent:#818cf8; --line:#1e293b; }}
    }}
    * {{ box-sizing: border-box; }}
    body {{
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
      background: var(--bg);
      color: var(--ink);
      margin: 0;
      padding: 24px 16px 80px;
      line-height: 1.55;
    }}
    main {{
      max-width: 720px;
      margin: 0 auto;
      background: var(--card);
      border: 1px solid var(--line);
      border-radius: 12px;
      padding: 32px 28px;
    }}
    h1 {{ margin: 0 0 4px; font-size: 1.6rem; }}
    .lede {{ color: var(--muted); margin-top: 0; font-size: 0.95rem; }}
    h2 {{ font-size: 1.1rem; margin-top: 28px; }}
    .contact-card {{
      margin: 16px 0 0;
      padding: 16px 18px;
      border: 1px solid var(--line);
      border-radius: 10px;
      background: rgba(67,56,202,0.04);
    }}
    .contact-card a {{ color: var(--accent); font-weight: 600; }}
    .row {{ display: flex; align-items: baseline; gap: 12px; flex-wrap: wrap; }}
    .row strong {{ min-width: 80px; color: var(--muted); font-weight: 500; }}
    ul {{ padding-left: 18px; }}
    li {{ margin: 6px 0; }}
    footer {{ margin-top: 28px; font-size: 0.85rem; color: var(--muted); }}
    a.btn {{
      display: inline-block; margin-top: 12px; padding: 10px 18px;
      background: var(--accent); color: #fff; text-decoration: none;
      border-radius: 8px; font-weight: 600;
    }}
    code {{ background: rgba(0,0,0,0.06); padding: 2px 6px; border-radius: 4px; font-size: 0.92em; }}
    @media (prefers-color-scheme: dark) {{
      code {{ background: rgba(255,255,255,0.08); }}
    }}
  </style>
</head>
<body>
  <main>
    <h1>Data Protection Officer</h1>
    <p class="lede">Nischint Technologies · DPDP Act 2023 §10 compliance surface</p>

    <div class="contact-card">
      <div class="row"><strong>Officer</strong><span>{DPO_NAME}</span></div>
      <div class="row"><strong>Email</strong><a href="mailto:{DPO_EMAIL}">{DPO_EMAIL}</a></div>
      <div class="row"><strong>SLA</strong><span>Initial acknowledgement within 7 days · Substantive response within {DPO_RESPONSE_SLA_DAYS} days</span></div>
      <a class="btn" href="mailto:{DPO_EMAIL}?subject=DPDP%20enquiry">Contact the DPO</a>
    </div>

    <h2>What the DPO can help with</h2>
    <ul>
      <li><strong>Right to access</strong> — request a copy of every piece of personal data we hold about you. Self-serve via <code>GET /api/privacy/me</code> in the app.</li>
      <li><strong>Right to correction</strong> — fix inaccuracies in your name, phone, emergency contacts, or health-source metadata.</li>
      <li><strong>Right to erasure</strong> — request deletion of your account and all linked records. Self-serve via the Privacy screen in the app, or email the DPO directly.</li>
      <li><strong>Right to withdraw consent</strong> — toggle off any specific data category (location, audio, health vitals, push, biometrics) from the in-app Privacy Settings.</li>
      <li><strong>Grievance redressal</strong> — if any of the above is not satisfactorily handled by self-serve flows, the DPO is your first point of escalation before the Data Protection Board of India.</li>
    </ul>

    <h2>What we hold about you (categories)</h2>
    <ul>
      <li>Account profile · email, name, role, phone (if provided)</li>
      <li>Location · only while a journey is active or in an SOS, with separately-revocable consent</li>
      <li>Health vitals · only via Health Connect / HealthKit, with separately-revocable consent</li>
      <li>Audio events · severity score only; raw audio never leaves your device</li>
      <li>Incident log · SOS, geofence, fall, and pickup events</li>
    </ul>

    <h2>DPDP Act §10 statement</h2>
    <p>
      Nischint Technologies is a Significant Data Fiduciary under the
      Digital Personal Data Protection Act, 2023. We have designated a
      Data Protection Officer responsible for: ensuring compliance
      with the Act, responding to Data Principal grievances, and
      acting as the point of contact for the Data Protection Board.
    </p>

    <footer>
      Last reviewed: 2026 · For technical / app issues, please use in-app support.<br>
      Machine-readable contact: <code><a href="/api/dpo.json" style="color:var(--accent)">/api/dpo.json</a></code>
    </footer>
  </main>
</body>
</html>"""
