"""When OBSERVABILITY_MOCK=true the events endpoint short-circuits to canned data."""
from __future__ import annotations

from app.services.observability.mocks import MOCK_EVENTS


def test_mock_events_shape() -> None:
    assert isinstance(MOCK_EVENTS, list)
    assert len(MOCK_EVENTS) >= 4

    required_keys = {"id", "kind", "timestamp", "severity", "title", "detail", "state"}
    for event in MOCK_EVENTS:
        missing = required_keys - set(event.keys())
        assert not missing, f"Mock event {event.get('id')} missing keys: {missing}"
        assert event["kind"] in {"alert", "agent_run"}


def test_mock_events_cover_states() -> None:
    states = {event["state"] for event in MOCK_EVENTS}
    severities = {event["severity"] for event in MOCK_EVENTS if event["kind"] == "alert"}
    assert {"open", "acknowledged", "resolved"} & states
    assert {"critical", "warning"} <= severities
