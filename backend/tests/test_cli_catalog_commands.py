from __future__ import annotations

from app.cli import main


def test_connectors_list_cli_prints_catalog(capsys) -> None:
    assert main(["connectors", "list"]) == 0
    output = capsys.readouterr().out
    assert "postgres" in output
    assert "stability" in output


def test_connectors_list_cli_prints_json(capsys) -> None:
    assert main(["connectors", "list", "--json"]) == 0
    output = capsys.readouterr().out
    assert '"slug": "postgres"' in output
    assert '"stability": "stable"' in output


def test_mcp_verify_alias_uses_catalog_verifier() -> None:
    assert main(["mcp", "verify"]) == 0
