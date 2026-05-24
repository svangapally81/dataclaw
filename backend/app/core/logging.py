import asyncio
import json
import logging
import queue
from datetime import UTC, datetime
from typing import Any

LOG_QUEUE_MAX = 10000
DRAIN_BATCH = 200
DRAIN_INTERVAL_SECONDS = 0.5

_log_queue: queue.Queue[dict[str, Any]] = queue.Queue(maxsize=LOG_QUEUE_MAX)


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        for key, value in record.__dict__.items():
            if key.startswith("_"):
                payload[key[1:]] = value
        return json.dumps(payload, default=str)


def _record_to_payload(record: logging.LogRecord) -> dict[str, Any]:
    context: dict[str, Any] = {}
    for key, value in record.__dict__.items():
        if key.startswith("_"):
            context[key[1:]] = value
    exception = None
    if record.exc_info:
        exception = logging.Formatter().formatException(record.exc_info)
    return {
        "timestamp": datetime.fromtimestamp(record.created, UTC),
        "level": record.levelname,
        "logger_name": record.name,
        "message": record.getMessage(),
        "context": context,
        "exception": exception,
    }


class DBLogHandler(logging.Handler):
    def emit(self, record: logging.LogRecord) -> None:
        try:
            payload = _record_to_payload(record)
            _log_queue.put_nowait(payload)
        except queue.Full:
            pass


def configure_logging() -> None:
    root = logging.getLogger()
    has_json = any(isinstance(handler.formatter, JsonFormatter) for handler in root.handlers)
    has_db = any(isinstance(handler, DBLogHandler) for handler in root.handlers)
    if has_json and has_db:
        return
    handlers: list[logging.Handler] = []
    if not has_json:
        stream = logging.StreamHandler()
        stream.setFormatter(JsonFormatter())
        handlers.append(stream)
    if not has_db:
        handlers.append(DBLogHandler())
    root.handlers = root.handlers + handlers if has_json or has_db else handlers
    root.setLevel(logging.INFO)


async def _drain_once() -> int:
    from app.db.session import SessionLocal
    from app.models.domain import LogEntry

    payloads: list[dict[str, Any]] = []
    while len(payloads) < DRAIN_BATCH:
        try:
            payloads.append(_log_queue.get_nowait())
        except queue.Empty:
            break
    if not payloads:
        return 0
    async with SessionLocal() as session:
        for payload in payloads:
            session.add(LogEntry(**payload))
        await session.commit()
    return len(payloads)


async def run_log_drainer() -> None:
    while True:
        try:
            await _drain_once()
        except asyncio.CancelledError:
            await _drain_once()
            raise
        except Exception:
            await asyncio.sleep(DRAIN_INTERVAL_SECONDS * 4)
            continue
        await asyncio.sleep(DRAIN_INTERVAL_SECONDS)
