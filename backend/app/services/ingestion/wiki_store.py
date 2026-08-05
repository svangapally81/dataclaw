from __future__ import annotations

import logging
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.domain import WikiPage
from app.services.ingestion.summarizer import WikiPageDraft, content_hash
from app.services.settings_store import hydrate_vector_store
from app.services.vector_store import vector_store

logger = logging.getLogger("dataclaw.ingestion.wiki_store")


def _format_scalar(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int | float):
        return str(value)
    return '"' + str(value).replace('"', '\\"') + '"'


def dump_frontmatter(frontmatter: dict[str, Any]) -> str:
    lines = ["---"]
    for key, value in frontmatter.items():
        if isinstance(value, list):
            lines.append(f"{key}:")
            for item in value:
                lines.append(f"  - {_format_scalar(item)}")
        elif isinstance(value, dict):
            lines.append(f"{key}:")
            for child_key, child_value in value.items():
                lines.append(f"  {child_key}: {_format_scalar(child_value)}")
        else:
            lines.append(f"{key}: {_format_scalar(value)}")
    lines.append("---")
    return "\n".join(lines)


def parse_frontmatter(markdown: str) -> tuple[dict[str, Any], str]:
    if not markdown.startswith("---\n"):
        return {}, markdown
    parts = markdown.split("---", 2)
    if len(parts) < 3:
        return {}, markdown
    raw = parts[1]
    body = parts[2]
    frontmatter: dict[str, Any] = {}
    current_key: str | None = None
    for line in raw.splitlines():
        if not line.strip():
            continue
        if line.startswith("  - ") and current_key:
            frontmatter.setdefault(current_key, []).append(line[4:].strip().strip('"'))
            continue
        if ":" in line and not line.startswith(" "):
            key, value = line.split(":", 1)
            current_key = key.strip()
            value = value.strip()
            if not value:
                frontmatter[current_key] = []
            elif value.startswith("[") and value.endswith("]"):
                frontmatter[current_key] = [part.strip().strip('"') for part in value[1:-1].split(",") if part.strip()]
            else:
                frontmatter[current_key] = value.strip('"')
    return frontmatter, body.lstrip()


def render_page(draft: WikiPageDraft) -> str:
    return f"{dump_frontmatter(draft.frontmatter)}\n\n{draft.body.rstrip()}\n"


class WikiStore:
    def __init__(self, root: Path | None = None) -> None:
        self.root = root or Path(get_settings().wiki_root)

    def disk_path(self, workspace_id: str, wiki_path: str) -> Path:
        clean = wiki_path.removeprefix("wiki/").lstrip("/")
        return self.root / workspace_id / clean

    async def upsert_page(self, session: AsyncSession, draft: WikiPageDraft) -> WikiPage:
        await hydrate_vector_store(session, draft.workspace_id)
        disk_path = self.disk_path(draft.workspace_id, draft.path)
        disk_path.parent.mkdir(parents=True, exist_ok=True)
        markdown = render_page(draft)
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=disk_path.parent, delete=False) as handle:
            handle.write(markdown)
            tmp_name = handle.name
        os.replace(tmp_name, disk_path)
        disk_mtime = datetime.fromtimestamp(disk_path.stat().st_mtime, UTC)
        page = await session.scalar(
            select(WikiPage).where(WikiPage.workspace_id == draft.workspace_id, WikiPage.path == draft.path)
        )
        if page is None:
            page = WikiPage(
                workspace_id=draft.workspace_id,
                path=draft.path,
                disk_path=str(disk_path),
                tier=draft.tier,
                source_type=draft.source_type,
                source_id=draft.source_id,
                title=draft.title,
                body=draft.body,
                frontmatter=draft.frontmatter,
                entities=draft.entities,
                content_hash=draft.content_hash,
                disk_mtime=disk_mtime,
            )
            session.add(page)
        else:
            page.disk_path = str(disk_path)
            page.tier = draft.tier
            page.source_type = draft.source_type
            page.source_id = draft.source_id
            page.title = draft.title
            page.body = draft.body
            page.frontmatter = draft.frontmatter
            page.entities = draft.entities
            page.content_hash = draft.content_hash
            page.disk_mtime = disk_mtime
        await session.flush()
        try:
            await vector_store.upsert_wiki_pages(draft.workspace_id, [page])
        except Exception as exc:
            logger.warning(
                "wiki_page_vector_upsert_skipped",
                extra={"_path": draft.path, "_error": exc.__class__.__name__},
            )
        return page

    async def get_page(self, session: AsyncSession, workspace_id: str, path: str) -> WikiPage | None:
        return await session.scalar(select(WikiPage).where(WikiPage.workspace_id == workspace_id, WikiPage.path == path))

    async def list_pages(
        self,
        session: AsyncSession,
        workspace_id: str,
        source_type: str | None = None,
        tier: int | None = None,
    ) -> list[WikiPage]:
        stmt = select(WikiPage).where(WikiPage.workspace_id == workspace_id)
        if source_type:
            stmt = stmt.where(WikiPage.source_type == source_type)
        if tier is not None:
            stmt = stmt.where(WikiPage.tier == tier)
        return list((await session.scalars(stmt.order_by(WikiPage.source_type, WikiPage.path))).all())

    async def delete_page(self, session: AsyncSession, workspace_id: str, path: str) -> bool:
        page = await self.get_page(session, workspace_id, path)
        if page is None:
            return False
        await vector_store.delete_ids(workspace_id, [vector_store.id_for_wiki_page(page)])
        try:
            Path(page.disk_path).unlink()
        except FileNotFoundError:
            logger.info("wiki_disk_file_missing_on_delete", extra={"_path": page.disk_path})
        await session.delete(page)
        return True

    async def refresh_from_disk(self, session: AsyncSession, page: WikiPage) -> bool:
        disk_path = Path(page.disk_path)
        if not disk_path.exists():
            return False
        disk_mtime = datetime.fromtimestamp(disk_path.stat().st_mtime, UTC)
        stored_mtime = page.disk_mtime
        if stored_mtime and stored_mtime.tzinfo is None:
            stored_mtime = stored_mtime.replace(tzinfo=UTC)
        if stored_mtime and disk_mtime <= stored_mtime:
            return False
        markdown = disk_path.read_text(encoding="utf-8")
        frontmatter, body = parse_frontmatter(markdown)
        page.frontmatter = frontmatter
        page.body = body
        page.entities = list(frontmatter.get("entities") or [])
        page.title = str(frontmatter.get("title") or page.title)
        page.content_hash = content_hash(markdown)
        page.disk_mtime = disk_mtime
        await session.flush()
        await hydrate_vector_store(session, page.workspace_id)
        await vector_store.upsert_wiki_pages(page.workspace_id, [page])
        return True
