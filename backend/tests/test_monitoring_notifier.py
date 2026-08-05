from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.models.domain import Alert, MonitoringConfig
from app.services.monitoring import notifier


def _alert() -> Alert:
    return Alert(
        workspace_id="ws1",
        fingerprint="alert-1",
        severity="critical",
        title="Pipeline failed",
        detail="daily_etl failed in task transform.",
        requires_approval=False,
    )


def test_smtp_recipients_accepts_string_and_list() -> None:
    assert notifier._smtp_recipients({"smtp_email": "a@example.com, b@example.com"}) == [
        "a@example.com",
        "b@example.com",
    ]
    assert notifier._smtp_recipients({"smtp_emails": ["c@example.com", " d@example.com "]}) == [
        "c@example.com",
        "d@example.com",
    ]


def test_send_smtp_alert_uses_configured_server(monkeypatch) -> None:
    sent: list[dict] = []

    class FakeSmtp:
        def __init__(self, host, port, timeout):  # noqa: ANN001
            sent.append({"host": host, "port": port, "timeout": timeout, "events": []})

        def __enter__(self):
            return self

        def __exit__(self, *args):  # noqa: ANN002
            return None

        def starttls(self):
            sent[-1]["events"].append("starttls")

        def login(self, user, password):  # noqa: ANN001
            sent[-1]["events"].append(("login", user, password))

        def send_message(self, message):  # noqa: ANN001
            sent[-1]["message"] = message

    monkeypatch.setattr(notifier.smtplib, "SMTP", FakeSmtp)

    notifier._send_smtp_alert(
        _alert(),
        ["ops@example.com"],
        SimpleNamespace(
            smtp_host="smtp.example.com",
            smtp_port=587,
            smtp_user="user",
            smtp_pass="pass",
            smtp_from="dataclaw@example.com",
            smtp_use_tls=True,
        ),
    )

    assert sent[0]["host"] == "smtp.example.com"
    assert sent[0]["events"] == ["starttls", ("login", "user", "pass")]
    assert sent[0]["message"]["To"] == "ops@example.com"
    assert "Pipeline failed" in sent[0]["message"].get_content()


@pytest.mark.asyncio
async def test_notify_alert_posts_pagerduty_event(monkeypatch) -> None:
    posts: list[dict] = []

    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

    class FakeClient:
        def __init__(self, timeout):  # noqa: ANN001
            self.timeout = timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):  # noqa: ANN002
            return None

        async def post(self, url, json=None):  # noqa: ANN001
            posts.append({"url": url, "json": json})
            return FakeResponse()

    monkeypatch.setattr(notifier.httpx, "AsyncClient", FakeClient)

    await notifier.notify_alert(
        _alert(),
        MonitoringConfig(
            workspace_id="ws1",
            agent_name="alerting",
            connector_id="conn1",
            enabled=True,
            notification_channels={"pagerduty_routing_key": "route-key"},
        ),
    )

    assert posts[0]["url"] == "https://events.pagerduty.com/v2/enqueue"
    assert posts[0]["json"]["routing_key"] == "route-key"
    assert posts[0]["json"]["event_action"] == "trigger"
    assert posts[0]["json"]["payload"]["severity"] == "critical"
