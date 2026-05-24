from __future__ import annotations

import os
from typing import Any

from tests.integration.acme.seed.saas.common import (
    ACME_DBT_FILES,
    SAAS_ENV,
    env_first,
    github_test_repo,
    missing_env,
    record_action,
    sdk_missing,
    skipped,
)


def _sandbox_repo(gh: Any) -> Any:
    repo_name = github_test_repo()
    if not repo_name:
        raise KeyError("GITHUB_TEST_REPO")
    return gh.get_repo(repo_name)


def seed_github() -> dict[str, Any]:
    missing = missing_env(SAAS_ENV["github"])
    repo_requirement = "GITHUB_TEST_REPO or GH_TEST_REPO"
    if repo_requirement in missing and os.getenv("GITHUB_REPOSITORY_OWNER") and os.getenv("ACME_GITHUB_REPO_NAME"):
        missing.remove(repo_requirement)
    if missing:
        return skipped(f"no creds: {', '.join(missing)}")
    try:
        from github import Github
        from github.GithubException import GithubException
    except ImportError as exc:
        return sdk_missing("PyGithub", exc)

    token = env_first("GITHUB_TEST_TOKEN", "GH_TEST_TOKEN")
    assert token is not None
    repo = _sandbox_repo(Github(token))
    branch = repo.default_branch or "main"
    actions: list[dict[str, str]] = []
    seeded_files: list[str] = []
    missing_files: list[str] = []
    write_errors: list[str] = []

    for path, content in ACME_DBT_FILES.items():
        message = f"seed Acme dbt fixture: {path}"
        try:
            current = repo.get_contents(path, ref=branch)
            if not isinstance(current, list):
                current_body = current.decoded_content.decode("utf-8", errors="replace")
                if current_body != content:
                    try:
                        repo.update_file(path, message, content, current.sha, branch=branch)
                        record_action(actions, "github", path, "updated")
                    except GithubException as exc:
                        write_errors.append(f"{path}: update failed ({exc.status})")
                else:
                    record_action(actions, "github", path, "exists")
                seeded_files.append(path)
        except GithubException as exc:
            if exc.status != 404:
                raise
            try:
                repo.create_file(path, message, content, branch=branch)
                record_action(actions, "github", path, "created")
                seeded_files.append(path)
            except GithubException as create_exc:
                missing_files.append(path)
                write_errors.append(f"{path}: create failed ({create_exc.status})")
    if missing_files:
        return skipped(f"github fixture files are missing and could not be created: {', '.join(missing_files)}")

    head_sha = repo.get_branch(branch).commit.sha
    issue_number = _ensure_issue(repo)
    pr_number = _ensure_pr(repo, branch, head_sha)
    workflow_run_repo, workflow_run_id = _workflow_run_target(repo.full_name, token)
    missing_live_targets = [
        name
        for name, value in {
            "issue_number": issue_number,
            "pr_number": pr_number,
            "workflow_run_id": workflow_run_id,
        }.items()
        if not value
    ]
    if missing_live_targets:
        return skipped(f"github seeded dbt files but missing live coverage target(s): {', '.join(missing_live_targets)}")
    return {
        "status": "seeded",
        "repo": repo.full_name,
        "default_branch": branch,
        "head_sha": head_sha,
        "issue_number": issue_number,
        "pr_number": pr_number,
        "workflow_run_repo": workflow_run_repo,
        "workflow_run_id": workflow_run_id,
        "files": sorted(seeded_files),
        "actions": actions,
        "write_warnings": write_errors,
    }


def _ensure_issue(repo: Any) -> int | None:
    title = "Acme coverage issue"
    for issue in repo.get_issues(state="open"):
        if issue.title == title:
            return issue.number
    try:
        issue = repo.create_issue(
            title=title,
            body="Seeded by the DataClaw Acme release-gate rig for read/write MCP coverage.",
        )
        return issue.number
    except Exception:
        try:
            for issue in repo.get_issues(state="all"):
                return issue.number
        except Exception:
            return None
    return None


def _ensure_pr(repo: Any, default_branch: str, head_sha: str) -> int | None:
    branch_name = "dataclaw-acme-coverage"
    title = "Acme coverage pull request"
    for pull in repo.get_pulls(state="open", head=f"{repo.owner.login}:{branch_name}"):
        if pull.title == title:
            return pull.number
    try:
        try:
            repo.create_git_ref(ref=f"refs/heads/{branch_name}", sha=head_sha)
        except Exception:
            repo.get_branch(branch_name)
        path = "models/staging/stg_customers.sql"
        content = ACME_DBT_FILES[path] + "-- Acme coverage branch marker\n"
        try:
            current = repo.get_contents(path, ref=branch_name)
            if not isinstance(current, list):
                repo.update_file(path, f"seed Acme coverage branch: {path}", content, current.sha, branch=branch_name)
        except Exception:
            repo.create_file(path, f"seed Acme coverage branch: {path}", content, branch=branch_name)
        pull = repo.create_pull(
            title=title,
            body="Seeded by the DataClaw Acme release-gate rig for PR MCP coverage.",
            head=branch_name,
            base=default_branch,
        )
        return pull.number
    except Exception:
        try:
            for pull in repo.get_pulls(state="all"):
                return pull.number
        except Exception:
            return None
    return None


def _workflow_run_target(repo_name: str, token: str) -> tuple[str, str | None]:
    if os.getenv("GITHUB_REPOSITORY") and os.getenv("GITHUB_RUN_ID"):
        return os.environ["GITHUB_REPOSITORY"], os.environ["GITHUB_RUN_ID"]
    return repo_name, _latest_workflow_run_id(repo_name, token)


def _latest_workflow_run_id(repo_name: str, token: str) -> str | None:
    try:
        import httpx
    except ImportError:
        return None
    with httpx.Client(base_url="https://api.github.com", timeout=30) as client:
        response = client.get(
            f"/repos/{repo_name}/actions/runs",
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
            },
            params={"per_page": 1},
        )
        if response.status_code >= 400:
            return None
        runs = response.json().get("workflow_runs") or []
        if not runs:
            return None
        return str(runs[0].get("id") or "") or None


__all__ = ["seed_github"]
