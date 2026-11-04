"""Structured, rotating diagnostics without prompts, passages, or credentials."""

import contextvars
import json
import logging
import os
import re
import traceback
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path

REQUEST_ID = contextvars.ContextVar("request_id", default="-")
LOGGER = logging.getLogger("financial_rag")
LOGGER.addHandler(logging.NullHandler())
LOGGER.propagate = False


def redact(text):
    """Redact configured secrets and common credential shapes, including exceptions."""
    text = str(text)
    for key, value in os.environ.items():
        if (
            any(
                word in key.upper()
                for word in ("API_KEY", "TOKEN", "PASSWORD", "SECRET", "SEC_USER_AGENT")
            )
            and len(value) >= 6
        ):
            text = text.replace(value, "[REDACTED]")
    text = re.sub(r"(?i)(bearer\s+)[\w.\-]+", r"\1[REDACTED]", text)
    text = re.sub(r"\bsk-[\w\-]{8,}", "[REDACTED]", text)
    return text


def sanitize(value):
    if isinstance(value, dict):
        return {key: sanitize(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [sanitize(item) for item in value]
    return redact(value) if isinstance(value, str) else value


class PrivateRotatingHandler(RotatingFileHandler):
    def _open(self):
        stream = super()._open()
        os.fchmod(stream.fileno(), 0o600)
        return stream


class JsonFormatter(logging.Formatter):
    def format(self, record):
        payload = {
            "timestamp": datetime.fromtimestamp(record.created, timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "request_id": REQUEST_ID.get(),
            "event": record.getMessage(),
        }
        payload.update(getattr(record, "fields", {}))
        if record.exc_info:
            payload["error_type"] = record.exc_info[0].__name__
            # Provider exception messages can echo prompts. Keep stack locations and type only.
            payload["exception_stack"] = [
                {"file": Path(frame.filename).name, "line": frame.lineno, "function": frame.name}
                for frame in traceback.extract_tb(record.exc_info[2])
            ]
        return json.dumps(sanitize(payload), default=str, ensure_ascii=False)


def event(name, level=logging.INFO, **fields):
    LOGGER.log(level, name, extra={"fields": fields})


def configure_logging(log_dir=None, level=None):
    """Replace only our handlers; safe to call twice in tests or embedded use."""
    level = (level or os.getenv("LOG_LEVEL", "INFO")).upper()
    if level not in ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"):
        raise ValueError("LOG_LEVEL must be DEBUG, INFO, WARNING, ERROR or CRITICAL.")
    directory = Path(log_dir or os.getenv("LOG_DIR", Path(__file__).resolve().parents[1] / "logs"))
    directory.mkdir(parents=True, exist_ok=True)
    directory.chmod(0o700)
    path = directory / "financial-rag.jsonl"
    path.touch(mode=0o600, exist_ok=True)
    path.chmod(0o600)
    for handler in list(LOGGER.handlers):
        LOGGER.removeHandler(handler)
        handler.close()
    formatter = JsonFormatter()
    rotating = PrivateRotatingHandler(path, maxBytes=5_000_000, backupCount=3, encoding="utf-8")
    console = logging.StreamHandler()
    for handler in (rotating, console):
        handler.setFormatter(formatter)
        LOGGER.addHandler(handler)
    LOGGER.setLevel(level)
    LOGGER.propagate = False
    # Provider clients can emit request URLs; project events expose only safe diagnostics.
    for name in ("httpx", "httpx2", "httpcore", "pinecone", "openai"):
        logging.getLogger(name).setLevel(logging.WARNING)
    event("logging.ready", level_name=level, rotation_bytes=5_000_000, backups=3)
    return path
