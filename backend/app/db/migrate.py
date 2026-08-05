import logging
from importlib import resources
from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import inspect, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.config import get_settings
from app.core.logging import configure_logging

configure_logging()
logger = logging.getLogger("dataclaw.migrate")


def _alembic_config() -> Config:
    alembic_root = resources.files("app").joinpath("alembic")
    ini_path = resources.files("app").joinpath("alembic.ini")
    config = Config(str(ini_path))
    config.set_main_option("script_location", str(alembic_root))
    config.set_main_option("sqlalchemy.url", get_settings().database_url)
    return config


def _ensure_sqlite_parent(database_url: str) -> None:
    url = make_url(database_url)
    if not url.drivername.startswith("sqlite") or not url.database or url.database == ":memory:":
        return
    Path(url.database).expanduser().parent.mkdir(parents=True, exist_ok=True)


async def _schema_state() -> tuple[bool, bool]:
    settings = get_settings()
    _ensure_sqlite_parent(settings.database_url)
    migrate_engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    try:
        async with migrate_engine.connect() as conn:
            return await conn.run_sync(
                lambda sync_conn: (
                    inspect(sync_conn).has_table("users"),
                    inspect(sync_conn).has_table("alembic_version"),
                )
            )
    finally:
        await migrate_engine.dispose()


async def _stamp_legacy_schema(revision: str) -> None:
    settings = get_settings()
    _ensure_sqlite_parent(settings.database_url)
    migrate_engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    try:
        async with migrate_engine.begin() as conn:
            await conn.execute(
                text(
                    "create table if not exists alembic_version ("
                    "version_num varchar(32) not null primary key"
                    ")"
                )
            )
            await conn.execute(text("delete from alembic_version"))
            await conn.execute(
                text("insert into alembic_version (version_num) values (:revision)"),
                {"revision": revision},
            )
    finally:
        await migrate_engine.dispose()


def main() -> None:
    import asyncio

    users_exists, alembic_exists = asyncio.run(_schema_state())
    alembic_config = _alembic_config()
    if users_exists and not alembic_exists:
        script = ScriptDirectory.from_config(alembic_config)
        head_revision = script.get_current_head()
        logger.info("legacy_schema_detected_stamping_head")
        asyncio.run(_stamp_legacy_schema(head_revision))
        logger.info("legacy_schema_stamp_complete")
        return
    logger.info("alembic_upgrade_begin")
    _ensure_sqlite_parent(get_settings().database_url)
    command.upgrade(alembic_config, "head")
    logger.info("alembic_upgrade_complete")


if __name__ == "__main__":
    main()
