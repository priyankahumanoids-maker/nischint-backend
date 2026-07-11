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

from fastapi import APIRouter
from fastapi.responses import HTMLResponse, JSONResponse

router = APIRouter(tags=["privacy", "dpdp"])

# Bump this when DPO details change.
DPO_NAME = "Nischint Data Protection Officer"
DPO_EMAIL = "privacy@nischint.care"
DPO_RESPONSE_SLA_DAYS = 30


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
