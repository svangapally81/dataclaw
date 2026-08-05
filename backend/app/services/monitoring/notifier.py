from __future__ import annotations

import asyncio
import logging
import smtplib
from email.message import EmailMessage

import httpx

from app.core.config import get_settings
from app.models.domain import Alert, MonitoringConfig

logger = logging.getLogger("dataclaw.monitoring")


async def notify_alert(alert: Alert, config: MonitoringConfig | None = None) -> None:
    settings = get_settings()
    channels = (config.notification_channels if config else {}) or {}
    slack_webhook = channels.get("slack_webhook")
    if slack_webhook:
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                await client.post(
                    slack_webhook,
                    json={"text": f"[{alert.severity}] {alert.title}\n{alert.detail}"},
                )
        except Exception:
            logger.exception("monitoring_slack_notify_failed", extra={"_alert_id": alert.id})

    recipients = _smtp_recipients(channels)
    if recipients:
        if settings.smtp_host and settings.smtp_from:
            try:
                await asyncio.to_thread(_send_smtp_alert, alert, recipients, settings)
            except Exception:
                logger.exception("monitoring_smtp_notify_failed", extra={"_alert_id": alert.id})
        else:
            logger.warning("monitoring_smtp_not_configured", extra={"_alert_id": alert.id})

    routing_key = str(channels.get("pagerduty_routing_key") or settings.pagerduty_routing_key or "").strip()
    if routing_key:
        try:
            await _send_pagerduty_alert(alert, routing_key)
        except Exception:
            logger.exception("monitoring_pagerduty_notify_failed", extra={"_alert_id": alert.id})


def _smtp_recipients(channels: dict) -> list[str]:
    raw = channels.get("smtp_emails") or channels.get("smtp_email")
    if raw is None:
        return []
    if isinstance(raw, str):
        values = raw.split(",")
    elif isinstance(raw, list):
        values = [str(value) for value in raw]
    else:
        return []
    return [value.strip() for value in values if value.strip()]


def _send_smtp_alert(alert: Alert, recipients: list[str], settings) -> None:  # noqa: ANN001
    message = EmailMessage()
    message["Subject"] = f"[DataClaw {alert.severity}] {alert.title}"
    message["From"] = settings.smtp_from or ""
    message["To"] = ", ".join(recipients)
    message.set_content(f"{alert.title}\n\nSeverity: {alert.severity}\n\n{alert.detail}")

    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=10) as smtp:
        if settings.smtp_use_tls:
            smtp.starttls()
        if settings.smtp_user and settings.smtp_pass:
            smtp.login(settings.smtp_user, settings.smtp_pass)
        smtp.send_message(message)


async def _send_pagerduty_alert(alert: Alert, routing_key: str) -> None:
    payload = {
        "routing_key": routing_key,
        "event_action": "trigger",
        "dedup_key": f"dataclaw:{alert.fingerprint or alert.id}",
        "payload": {
            "summary": alert.title,
            "source": getattr(alert, "connector_slug", None) or "dataclaw",
            "severity": _pagerduty_severity(alert.severity),
            "custom_details": {
                "alert_id": alert.id,
                "detail": alert.detail,
                "resolved": alert.resolved,
                "requires_approval": alert.requires_approval,
            },
        },
    }
    async with httpx.AsyncClient(timeout=10) as client:
        response = await client.post("https://events.pagerduty.com/v2/enqueue", json=payload)
        response.raise_for_status()


def _pagerduty_severity(severity: str) -> str:
    normalized = severity.lower()
    if normalized in {"critical", "error"}:
        return "critical"
    if normalized in {"warning", "warn"}:
        return "warning"
    return "info"
