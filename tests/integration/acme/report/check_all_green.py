from __future__ import annotations

from pathlib import Path

ACME_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = ACME_ROOT.parents[2]
REPORTS = [REPO_ROOT / "docs" / "MCP_COVERAGE.md", REPO_ROOT / "docs" / "E2E_REPORT.md"]


def main() -> int:
    missing = [path for path in REPORTS if not path.exists()]
    if missing:
        print("Missing reports:")
        for path in missing:
            print(f"- {path.relative_to(REPO_ROOT)}")
        return 1
    red: list[str] = []
    for path in REPORTS:
        for line in path.read_text().splitlines():
            if "| red |" in line or "| pending |" in line:
                red.append(f"{path.relative_to(REPO_ROOT)}: {line}")
    if red:
        print("Acme rig has red rows:")
        for line in red:
            print(line)
        return 1
    print("All Acme report rows are green.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
