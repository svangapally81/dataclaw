from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.domain import WikiPage
from app.services.ingestion.wiki_store import WikiStore


async def reconcile_wiki_disk_edits(session: AsyncSession, workspace_id: str | None = None) -> int:
    stmt = select(WikiPage)
    if workspace_id:
        stmt = stmt.where(WikiPage.workspace_id == workspace_id)
    pages = list((await session.scalars(stmt)).all())
    store = WikiStore()
    changed = 0
    for page in pages:
        if await store.refresh_from_disk(session, page):
            changed += 1
    await session.commit()
    return changed
