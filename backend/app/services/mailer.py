"""Outbound email. Silently disabled when SMTP is not configured."""

from __future__ import annotations

import smtplib
from email.message import EmailMessage

from app.core.config import settings
from app.core.logging import get_logger
from app.models import Severity

logger = get_logger(__name__)

SEVERITY_PREFIX = {
    Severity.info: "[INFO]",
    Severity.warning: "[WARNING]",
    Severity.critical: "[CRITICAL]",
}


def send_email(recipients: list[str], subject: str, body: str, html: str | None = None) -> bool:
    if not settings.mail_enabled:
        logger.debug("SMTP not configured; skipping email '%s'", subject)
        return False
    if not recipients:
        return False

    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = settings.smtp_from
    message["To"] = ", ".join(recipients)
    message.set_content(body)
    if html:
        message.add_alternative(html, subtype="html")

    try:
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=30) as server:
            if settings.smtp_tls:
                server.starttls()
            if settings.smtp_user:
                server.login(settings.smtp_user, settings.smtp_password)
            server.send_message(message)
        logger.info("Sent '%s' to %s recipient(s)", subject, len(recipients))
        return True
    except (smtplib.SMTPException, OSError) as exc:
        logger.error("Could not send email '%s': %s", subject, exc)
        return False


def send_alert_email(
    recipients: list[str], title: str, message: str, severity: Severity
) -> bool:
    prefix = SEVERITY_PREFIX.get(severity, "[ALERT]")
    subject = f"{prefix} {settings.project_name}: {title}"
    body = (
        f"{message}\n\n"
        f"Open the monitoring dashboard: {settings.public_url}/monitoring/alerts\n\n"
        f"-- {settings.project_name}"
    )
    html = f"""
    <div style="font-family:system-ui,sans-serif;max-width:560px">
      <p style="font-size:13px;letter-spacing:.08em;text-transform:uppercase;color:#64748b">
        {prefix.strip('[]')}
      </p>
      <h2 style="margin:.2em 0;color:#0f172a">{title}</h2>
      <p style="color:#334155;line-height:1.6">{message}</p>
      <p><a href="{settings.public_url}/monitoring/alerts"
            style="background:#2563eb;color:#fff;padding:10px 18px;border-radius:6px;
                   text-decoration:none;display:inline-block">Open dashboard</a></p>
      <p style="color:#94a3b8;font-size:12px">Sent by {settings.project_name}</p>
    </div>
    """
    return send_email(recipients, subject, body, html)
