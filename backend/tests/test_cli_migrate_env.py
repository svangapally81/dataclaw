from __future__ import annotations

import os


def test_cmd_migrate_loads_dataclaw_home_env(monkeypatch, tmp_path) -> None:
    """`dataclaw migrate` must read DATABASE_URL from ~/.dataclaw/.env."""
    import app.cli as cli
    import app.db.migrate as migrate_mod

    env_path = tmp_path / ".env"
    env_path.write_text(
        "DATABASE_URL=sqlite+aiosqlite:///tmp/dataclaw-home.sqlite\n"
        "MASTER_KEY=home-master-key\n"
    )
    captured: dict[str, str | None] = {}

    def fake_main() -> None:
        captured["DATABASE_URL"] = os.environ.get("DATABASE_URL")
        captured["MASTER_KEY"] = os.environ.get("MASTER_KEY")

    monkeypatch.setattr(cli, "DATA_DIR", tmp_path)
    monkeypatch.setattr(cli, "ENV_PATH", env_path)
    monkeypatch.setattr(migrate_mod, "main", fake_main)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("MASTER_KEY", raising=False)
    monkeypatch.delenv("DATACLAW_HOME", raising=False)

    # Drive through main() so the env loader runs.
    assert cli.main(["migrate"]) == 0
    assert captured["DATABASE_URL"] == "sqlite+aiosqlite:///tmp/dataclaw-home.sqlite"
    assert captured["MASTER_KEY"] == "home-master-key"
    assert os.environ["DATACLAW_HOME"] == str(tmp_path)


def test_cmd_migrate_preserves_explicit_process_env(monkeypatch, tmp_path) -> None:
    """Process env beats the on-disk .env file (setdefault semantics)."""
    import app.cli as cli
    import app.db.migrate as migrate_mod

    env_path = tmp_path / ".env"
    env_path.write_text("DATABASE_URL=sqlite+aiosqlite:///tmp/dataclaw-home.sqlite\n")
    captured: dict[str, str | None] = {}

    def fake_main() -> None:
        captured["DATABASE_URL"] = os.environ.get("DATABASE_URL")

    monkeypatch.setattr(cli, "DATA_DIR", tmp_path)
    monkeypatch.setattr(cli, "ENV_PATH", env_path)
    monkeypatch.setattr(migrate_mod, "main", fake_main)
    monkeypatch.setenv("DATABASE_URL", "sqlite+aiosqlite:///tmp/explicit.sqlite")

    assert cli.main(["migrate"]) == 0
    assert captured["DATABASE_URL"] == "sqlite+aiosqlite:///tmp/explicit.sqlite"
