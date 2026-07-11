"""
Email Service — SendGrid email delivery for guardian invites and safety alerts.
Gracefully degrades if SENDGRID_API_KEY is not configured.
"""
import os
import logging
from typing import Optional

logger = logging.getLogger(__name__)


def _get_sendgrid_key():
    key = os.environ.get("SENDGRID_API_KEY")
    if not key:
        try:
            from dotenv import load_dotenv
            load_dotenv(os.path.join(os.path.dirname(__file__), '..', '..', '.env'))
            key = os.environ.get("SENDGRID_API_KEY")
        except Exception:
            pass
    return key


def _get_sender():
    return os.environ.get("SENDER_EMAIL", "alerts@nischint.app")


APP_NAME = "Nischint Safety"


def _is_available() -> bool:
    return bool(_get_sendgrid_key())


def send_email(to: str, subject: str, html_content: str, text_content: Optional[str] = None) -> bool:
    """Send an email via SendGrid. Returns True on success.

    `text_content` (optional) supplies a plain-text alternative that
    SendGrid stitches into a multipart/alternative MIME body. Clients
    that can't render HTML — and good-citizen anti-spam filters — read
    the text part. Pass it whenever you have a meaningful plaintext
    version; otherwise SendGrid auto-strips the HTML.
    """
    if not _is_available():
        logger.info(f"SendGrid not configured — email to {to} stored but not sent")
        return False

    try:
        from sendgrid import SendGridAPIClient
        from sendgrid.helpers.mail import Mail

        if text_content is not None:
            message = Mail(
                from_email=_get_sender(),
                to_emails=to,
                subject=subject,
                plain_text_content=text_content,
                html_content=html_content,
            )
        else:
            message = Mail(
                from_email=_get_sender(),
                to_emails=to,
                subject=subject,
                html_content=html_content,
            )
        sg = SendGridAPIClient(_get_sendgrid_key())
        response = sg.send(message)
        sent = response.status_code in (200, 202)
        if sent:
            logger.info(f"Email sent to {to}: {subject}")
        else:
            logger.warning(f"Email send failed ({response.status_code}): {to}")
        return sent
    except Exception as e:
        logger.error(f"SendGrid error: {e}")
        return False


def send_guardian_invite_email(
    to_email: str,
    inviter_name: str,
    guardian_name: Optional[str],
    relationship: str,
    invite_url: str,
) -> bool:
    """Send a guardian invite email with a beautiful HTML template."""
    recipient_greeting = guardian_name or "there"
    subject = f"You've been added as a guardian on {APP_NAME}"

    html = f"""
    <!DOCTYPE html>
    <html lang="en">
    <head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"></head>
    <body style="margin:0;padding:0;background-color:#020617;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;">
      <table width="100%" cellpadding="0" cellspacing="0" style="background-color:#020617;padding:40px 20px;">
        <tr><td align="center">
          <table width="420" cellpadding="0" cellspacing="0" style="background-color:#0f172a;border-radius:16px;border:1px solid #1e293b;overflow:hidden;">
            <!-- Header -->
            <tr><td style="background:linear-gradient(135deg,#0d9488,#0891b2);padding:32px 24px;text-align:center;">
              <div style="width:56px;height:56px;background:rgba(255,255,255,0.15);border-radius:50%;margin:0 auto 12px;line-height:56px;font-size:24px;">&#x1F6E1;</div>
              <h1 style="color:#ffffff;font-size:22px;margin:0 0 4px;">{APP_NAME}</h1>
              <p style="color:rgba(255,255,255,0.8);font-size:13px;margin:0;">AI-Powered Safety Platform</p>
            </td></tr>

            <!-- Body -->
            <tr><td style="padding:28px 24px;">
              <h2 style="color:#e2e8f0;font-size:18px;margin:0 0 12px;">Hi {recipient_greeting},</h2>
              <p style="color:#94a3b8;font-size:14px;line-height:1.6;margin:0 0 20px;">
                <strong style="color:#e2e8f0;">{inviter_name}</strong> has added you as a
                <strong style="color:#2dd4bf;">{relationship.replace('_', ' ')}</strong>
                on {APP_NAME}.
              </p>

              <p style="color:#94a3b8;font-size:14px;line-height:1.6;margin:0 0 24px;">
                As a guardian, you'll receive real-time safety alerts, SOS notifications,
                and AI-powered risk assessments to help protect your loved ones.
              </p>

              <!-- CTA Button -->
              <table width="100%" cellpadding="0" cellspacing="0">
                <tr><td align="center">
                  <a href="{invite_url}" style="display:inline-block;background-color:#0d9488;color:#ffffff;text-decoration:none;font-weight:bold;font-size:15px;padding:14px 32px;border-radius:12px;">
                    Accept Guardian Invite
                  </a>
                </td></tr>
              </table>

              <!-- Features -->
              <table width="100%" cellpadding="0" cellspacing="0" style="margin-top:24px;border-top:1px solid #1e293b;padding-top:20px;">
                <tr><td style="color:#64748b;font-size:12px;padding:6px 0;">&#x2705; Real-time safety alerts</td></tr>
                <tr><td style="color:#64748b;font-size:12px;padding:6px 0;">&#x1F6A8; SOS emergency notifications</td></tr>
                <tr><td style="color:#64748b;font-size:12px;padding:6px 0;">&#x1F4CD; Live location tracking during sessions</td></tr>
                <tr><td style="color:#64748b;font-size:12px;padding:6px 0;">&#x1F9E0; AI-powered risk assessments</td></tr>
              </table>

              <p style="color:#475569;font-size:12px;margin:20px 0 0;text-align:center;">
                This invite expires in 48 hours.
              </p>
            </td></tr>

            <!-- Footer -->
            <tr><td style="background-color:#0b1120;padding:16px 24px;text-align:center;border-top:1px solid #1e293b;">
              <p style="color:#475569;font-size:11px;margin:0;">{APP_NAME} — Protecting What Matters Most</p>
            </td></tr>
          </table>
        </td></tr>
      </table>
    </body>
    </html>
    """

    return send_email(to_email, subject, html)


def send_sos_alert_email(
    to_email: str,
    user_name: str,
    location: Optional[dict] = None,
) -> bool:
    """Send SOS alert email to a guardian."""
    from app.services.notification_formatter import email_sos
    subject, html = email_sos(user_name, location)
    return send_email(to_email, subject, html)


def send_fall_alert_email(
    to_email: str,
    user_name: str,
    location: Optional[dict] = None,
) -> bool:
    """Send fall detection email to a guardian."""
    from app.services.notification_formatter import email_fall
    subject, html = email_fall(user_name, location)
    return send_email(to_email, subject, html)


def send_zone_breach_email(
    to_email: str,
    user_name: str,
    zone_name: str = "safe zone",
    location: Optional[dict] = None,
) -> bool:
    """Send safe zone breach email to a guardian."""
    from app.services.notification_formatter import email_zone_breach
    subject, html = email_zone_breach(user_name, zone_name, location)
    return send_email(to_email, subject, html)


def send_journey_started_email(
    to_email: str,
    user_name: str,
    destination: str = "",
) -> bool:
    """Send journey started email to a guardian."""
    from app.services.notification_formatter import email_journey_started
    subject, html = email_journey_started(user_name, destination)
    return send_email(to_email, subject, html)


def send_arrived_safely_email(
    to_email: str,
    user_name: str,
    destination: str = "",
) -> bool:
    """Send arrived safely email to a guardian."""
    from app.services.notification_formatter import email_arrived_safely
    subject, html = email_arrived_safely(user_name, destination)
    return send_email(to_email, subject, html)


def send_escalation_email(
    to_email: str,
    user_name: str,
    level: int,
    incident_type: str,
) -> bool:
    """Send escalation email to a guardian or operator."""
    from app.services.notification_formatter import email_escalation
    subject, html = email_escalation(user_name, level, incident_type)
    return send_email(to_email, subject, html)
