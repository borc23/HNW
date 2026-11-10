import logging
import sys
import uuid
from typing import Any

import structlog


def configure_logging(level: str = "INFO", *, json: bool = True) -> None:
    renderer: structlog.typing.Processor = (
        structlog.processors.JSONRenderer() if json else structlog.dev.ConsoleRenderer()
    )
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.dict_tracebacks,
            renderer,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.getLevelName(level)),
        logger_factory=structlog.PrintLoggerFactory(file=sys.stdout),
        cache_logger_on_first_use=False,
    )


def get_logger(name: str | None = None, **initial: Any) -> structlog.typing.FilteringBoundLogger:
    return structlog.get_logger(name, **initial)


def new_correlation_id() -> str:
    return uuid.uuid4().hex


def bind_context(**values: Any) -> None:
    """Attach values (e.g. request_id, job_id) to all log lines in the current context."""
    structlog.contextvars.bind_contextvars(**values)


def clear_context() -> None:
    structlog.contextvars.clear_contextvars()
