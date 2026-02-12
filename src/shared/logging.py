import json
import logging
import os
import sys
from datetime import datetime, timezone
from typing import Any, Dict


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: Dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        for key in ("delivery_id", "repo", "pr_number", "sha", "correlation_id"):
            value = getattr(record, key, None)
            if value is not None:
                payload[key] = value

        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)

        if hasattr(record, "extra") and isinstance(record.extra, dict):
            payload.update(record.extra)

        return json.dumps(payload, default=str)


_LOGGING_CONFIGURED = False


def configure_logging() -> None:
    global _LOGGING_CONFIGURED
    if _LOGGING_CONFIGURED:
        return

    root = logging.getLogger()
    root.handlers = []

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root.addHandler(handler)
    root.setLevel(os.getenv("LOG_LEVEL", "INFO"))
    _LOGGING_CONFIGURED = True


class ContextAdapter(logging.LoggerAdapter):
    def process(self, msg, kwargs):
        extra = kwargs.get("extra", {})
        merged = dict(self.extra)
        merged.update(extra)
        kwargs["extra"] = merged
        return msg, kwargs


def get_logger(name: str, **context: Any) -> ContextAdapter:
    configure_logging()
    return ContextAdapter(logging.getLogger(name), context)
