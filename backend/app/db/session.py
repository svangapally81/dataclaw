from collections.abc import AsyncIterator
from pathlib import Path

from sqlalchemy import event
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import get_settings

settings = get_settings()


def ensure_sqlite_parent(database_url: str) -> None:
    url = make_url(database_url)
    if not url.drivername.startswith("sqlite") or not url.database or url.database == ":memory:":
        return
    Path(url.database).expanduser().parent.mkdir(parents=True, exist_ok=True)


ensure_sqlite_parent(settings.database_url)
ensure_sqlite_parent(settings.demo_database_url)


def _is_sqlite_url(database_url: str) -> bool:
    return make_url(database_url).drivername.startswith("sqlite")


def _create_app_engine(database_url: str):
    kwargs = {"pool_pre_ping": True}
    if _is_sqlite_url(database_url):
        kwargs["connect_args"] = {"timeout": 30}
    created = create_async_engine(database_url, **kwargs)
    if _is_sqlite_url(database_url):
        @event.listens_for(created.sync_engine, "connect")
        def _configure_sqlite(dbapi_connection, _connection_record) -> None:
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA busy_timeout=30000")
            cursor.close()

    return created


engine = _create_app_engine(settings.database_url)
SessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def get_session() -> AsyncIterator[AsyncSession]:
    async with SessionLocal() as session:
        session.info["session_factory"] = SessionLocal
        yield session
