from __future__ import annotations

import sys
import types

import pytest

from app.services.mcp_executor import (
    McpExecutionError,
    _redshift_cluster_action,
    _redshift_list_clusters,
)


class FakeRedshiftClient:
    calls: list[tuple[str, dict]] = []

    def describe_clusters(self):
        self.calls.append(("describe_clusters", {}))
        return {"Clusters": [{"ClusterIdentifier": "analytics-prod", "ClusterStatus": "available"}]}

    def pause_cluster(self, **kwargs):
        self.calls.append(("pause_cluster", kwargs))
        return {"Cluster": {"ClusterIdentifier": kwargs["ClusterIdentifier"], "ClusterStatus": "pausing"}}

    def resume_cluster(self, **kwargs):
        self.calls.append(("resume_cluster", kwargs))
        return {"Cluster": {"ClusterIdentifier": kwargs["ClusterIdentifier"], "ClusterStatus": "resuming"}}


@pytest.fixture(autouse=True)
def fake_boto3(monkeypatch):
    FakeRedshiftClient.calls = []
    fake_module = types.ModuleType("boto3")
    fake_module.client = lambda service, **kwargs: FakeRedshiftClient()
    monkeypatch.setitem(sys.modules, "boto3", fake_module)


def test_redshift_cluster_tools_use_boto3_client() -> None:
    credentials = {"region": "us-east-1", "cluster_identifier": "analytics-prod"}

    listed = _redshift_list_clusters(credentials)
    paused = _redshift_cluster_action(credentials, {}, "write_pause_cluster", "agent-1")
    resumed = _redshift_cluster_action(credentials, {"cluster_identifier": "analytics-prod"}, "write_resume_cluster", "agent-1")

    assert listed["clusters"][0]["ClusterIdentifier"] == "analytics-prod"
    assert paused["cluster"]["ClusterStatus"] == "pausing"
    assert resumed["cluster"]["ClusterStatus"] == "resuming"
    assert ("pause_cluster", {"ClusterIdentifier": "analytics-prod"}) in FakeRedshiftClient.calls
    assert ("resume_cluster", {"ClusterIdentifier": "analytics-prod"}) in FakeRedshiftClient.calls


def test_redshift_cluster_identifier_rejects_invalid_values() -> None:
    with pytest.raises(McpExecutionError, match="cluster_identifier"):
        _redshift_cluster_action({}, {"cluster_identifier": "1bad"}, "write_pause_cluster", "agent-1")
