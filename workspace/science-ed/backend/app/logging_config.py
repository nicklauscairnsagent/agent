"""
Structured JSON logging configuration for the ScienceEd backend.

Provides:
- JSONFormatter: outputs JSON lines with timestamp, level, logger, message
- LoggingMiddleware: FastAPI middleware that logs request/response details
- setup_logging(): configures root logger and FastAPI/Uvicorn loggers
- redact_url(): safely redact DB URLs for startup logging

Usage in main.py:
    from app.logging_config import setup_logging, LoggingMiddleware
    setup_logging(level=settings.log_level)
    app.add_middleware(LoggingMiddleware)
"""

from __future__ import annotations

import json
import logging
import logging.config
import os
import re
import time
from collections.abc import Callable
from typing import Any

from starlette.datastructures import Headers
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp, Message, Receive, Scope, Send


# ---------------------------------------------------------------------------
# JSON formatter
# ---------------------------------------------------------------------------

class JSONFormatter(logging.Formatter):
    """Output log records as single-line JSON objects.

    Fields: timestamp (ISO‑8601), level, logger, module, function, line,
    message, plus any extra keyword args attached to the record.
    """

    def format(self, record: logging.LogRecord) -> str:
        obj: dict[str, Any] = {
            "timestamp": self.formatTime(record, datefmt="%Y-%m-%dT%H:%M:%S"),
            "level": record.levelname,
            "logger": record.name,
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
            "message": record.getMessage(),
        }
        # Include exception info if present
        if record.exc_info and record.exc_info[0] is not None:
            obj["exception"] = self.formatException(record.exc_info)
        if record.stack_info:
            obj["stack_info"] = record.stack_info

        # Extra fields attached via logger.info("msg", extra={"key": val})
        for key, val in record.__dict__.items():
            if key not in (
                "args", "asctime", "created", "exc_info", "exc_text",
                "filename", "funcName", "levelname", "levelno", "lineno",
                "module", "msecs", "message", "msg", "name", "pathname",
                "process", "processName", "relativeCreated", "stack_info",
                "thread", "threadName",
            ):
                obj[key] = _serialise(val)

        return json.dumps(obj, default=str, ensure_ascii=False)


def _serialise(val: Any) -> Any:
    """Best-effort serialisation – convert non‑JSON types to str."""
    if isinstance(val, (str, int, float, bool)) or val is None:
        return val
    try:
        json.dumps(val)
        return val
    except (TypeError, ValueError):
        return str(val)


# ---------------------------------------------------------------------------
# FastAPI middleware for structured request/response logging
# ---------------------------------------------------------------------------

class LoggingMiddleware:
    """Log every HTTP request with method, path, status, duration, client IP.

    * 4xx responses are logged at WARNING level.
    * 5xx responses are logged at ERROR level.
    * All others at INFO level.

    Attach this middleware *after* CORS so client IP resolution works.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app
        self.logger = logging.getLogger("science-ed.api")

    async def __call__(
        self, scope: Scope, receive: Receive, send: Send
    ) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request = Request(scope)
        start = time.monotonic()
        status_code = 0
        body_sent = 0

        # Capture client IP (respect X-Forwarded-For / X-Real-IP)
        client_ip = self._resolve_client_ip(request)

        async def _send(message: Message) -> None:
            nonlocal status_code, body_sent
            if message["type"] == "http.response.start":
                status_code = message["status"]
            elif message["type"] == "http.response.body":
                body_sent += len(message.get("body", b""))
            await send(message)

        try:
            await self.app(scope, receive, _send)
        except Exception as exc:
            status_code = 500
            self.logger.error(
                "Unhandled exception",
                extra={
                    "method": request.method,
                    "path": request.url.path,
                    "client_ip": client_ip,
                    "duration_ms": _elapsed_ms(start),
                },
                exc_info=True,
            )
            raise
        finally:
            duration_ms = _elapsed_ms(start)
            log_data = {
                "method": request.method,
                "path": request.url.path,
                "status": status_code,
                "duration_ms": duration_ms,
                "client_ip": client_ip,
                "bytes_sent": body_sent,
            }

            if 500 <= status_code < 600:
                self.logger.error("", extra=log_data)  # type: ignore[arg-type]
            elif 400 <= status_code < 500:
                self.logger.warning("", extra=log_data)  # type: ignore[arg-type]
            else:
                self.logger.info("", extra=log_data)  # type: ignore[arg-type]

    @staticmethod
    def _resolve_client_ip(request: Request) -> str:
        forwarded = request.headers.get("X-Forwarded-For")
        if forwarded:
            return forwarded.split(",")[0].strip()
        real_ip = request.headers.get("X-Real-IP")
        if real_ip:
            return real_ip.strip()
        client_host = request.client.host if request.client else ""
        return client_host


def _elapsed_ms(start: float) -> int:
    return int((time.monotonic() - start) * 1000)


# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------

_LOGGING_CONFIG: dict[str, Any] = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "json": {
            "()": JSONFormatter,
        },
        # Keep a simple text formatter for local dev
        "standard": {
            "format": "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            "datefmt": "%H:%M:%S",
        },
    },
    "filters": {
        # Suppress health-check noise from the request log
        "healthcheck_filter": {
            "()": "app.logging_config._HealthCheckFilter",
        },
    },
    "handlers": {
        "console_json": {
            "class": "logging.StreamHandler",
            "formatter": "json",
            "level": "DEBUG",
            "stream": "ext://sys.stdout",
            "filters": ["healthcheck_filter"],
        },
        "console_standard": {
            "class": "logging.StreamHandler",
            "formatter": "standard",
            "level": "DEBUG",
            "stream": "ext://sys.stdout",
        },
    },
    "loggers": {
        "science-ed": {
            "level": "INFO",
            "handlers": ["console_json"],
            "propagate": False,
        },
        "science-ed.api": {
            "level": "INFO",
            "handlers": ["console_json"],
            "propagate": False,
        },
        # Silence noisy libraries at DEBUG level
        "sqlalchemy.engine": {
            "level": "WARNING",
            "handlers": ["console_json"],
            "propagate": False,
        },
        "httpx": {
            "level": "WARNING",
            "handlers": ["console_json"],
            "propagate": False,
        },
        "jose": {
            "level": "WARNING",
            "handlers": ["console_json"],
            "propagate": False,
        },
    },
    "root": {
        "level": "WARNING",
        "handlers": ["console_json"],
    },
}


class _HealthCheckFilter(logging.Filter):
    """Suppress health-check request log lines to reduce noise."""

    def filter(self, record: logging.LogRecord) -> bool:
        msg = record.getMessage() if hasattr(record, "msg") else str(record.msg)
        path = getattr(record, "path", "")
        return "/health" not in path and "/health" not in msg


def setup_logging(*, level: str = "INFO", json_format: bool = True) -> None:
    """Configure the root logger and science-ed loggers.

    Parameters
    ----------
    level : str
        Log level (DEBUG, INFO, WARNING, ERROR). Defaults to ``INFO``.
    json_format : bool
        When True (default) uses JSON output; False uses human-readable text.
    """
    config = _LOGGING_CONFIG.copy()
    handler_key = "console_json" if json_format else "console_standard"

    # Override level from env if set
    env_level = os.environ.get("SCIENCE_ED_LOG_LEVEL", "").upper().strip()
    effective = env_level if env_level in ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL") else level.upper()

    # Set science-ed root logger level
    config["loggers"]["science-ed"]["level"] = effective
    config["loggers"]["science-ed"]["handlers"] = [handler_key]
    config["loggers"]["science-ed.api"]["level"] = effective
    config["loggers"]["science-ed.api"]["handlers"] = [handler_key]

    logging.config.dictConfig(config)

    # Patch uvicorn access log to use JSON format
    _patch_uvicorn_access()


def _patch_uvicorn_access() -> None:
    """Redirect uvicorn.access logger to our JSON handler."""
    uvicorn_logger = logging.getLogger("uvicorn.access")
    uvicorn_logger.handlers.clear()
    uvicorn_logger.propagate = False
    # Let our middleware handle request logging instead
    uvicorn_logger.disabled = True

    uvicorn_error = logging.getLogger("uvicorn.error")
    uvicorn_error.handlers.clear()
    uvicorn_error.propagate = True


# ---------------------------------------------------------------------------
# Redaction helper
# ---------------------------------------------------------------------------

_DB_URL_PATTERN = re.compile(
    r"(\w+://\w+:)([^@]+)(@.+)"
)


def redact_url(url: str) -> str:
    """Redact passwords from a connection URL for safe logging.

    >>> redact_url("postgresql+asyncpg://user:secret@host:5432/db")
    'postgresql+asyncpg://user:***@host:5432/db'
    """
    match = _DB_URL_PATTERN.match(url)
    if match:
        return f"{match.group(1)}***{match.group(3)}"
    return url


# ---------------------------------------------------------------------------
# Sentry PII filter — before_send hook for FERPA/COPPA compliance
# ---------------------------------------------------------------------------

_SENTRY_PII_FIELDS = frozenset({"email", "username", "ip_address"})

_SENTRY_REQUEST_DATA_FIELDS = frozenset({
    "email", "password", "password_confirm", "current_password",
    "new_password", "secret", "token", "access_token", "refresh_token",
    "api_key", "ssn", "phone", "phone_number",
})

_SENTRY_SENSITIVE_HEADERS = frozenset({
    "authorization", "cookie", "x-api-key", "x-forwarded-for",
    "x-real-ip", "x-auth-token",
})


def sentry_before_send(event: dict, hint: dict) -> dict | None:
    """Strip PII from Sentry events before they leave the server.

    FERPA/COPPA compliance hook. Scrubs:
    - ``user.email``, ``user.username``, ``user.ip_address``
    - JWT ``sub`` claim from user context
    - Request body fields matching sensitive field names
    - Authorization / Cookie headers
    - Any extra field ending in ``_email`` or containing JWT tokens
    - ``contexts`` entries with PII-like field names

    Returns the sanitized event (or ``None`` to drop — currently always
    returns the event so we don't lose error data, just sanitise it).
    """
    stripped_count = 0

    # ------------------------------------------------------------------
    # 1. User context — strip email, username, ip_address, JWT sub
    # ------------------------------------------------------------------
    user = event.get("user")
    if user and isinstance(user, dict):
        for field in _SENTRY_PII_FIELDS:
            if field in user and user[field]:
                user[field] = ""
                stripped_count += 1
        # Strip JWT 'sub' claim if present (looks like a user ID but
        # could leak the JWT subject identifier across environments)
        if "sub" in user and user["sub"]:
            user["sub"] = ""
            stripped_count += 1

    # ------------------------------------------------------------------
    # 2. Request data — sensitive body fields
    # ------------------------------------------------------------------
    request = event.get("request")
    if request and isinstance(request, dict):
        # Request body (parsed form / JSON data)
        data = request.get("data")
        if data and isinstance(data, dict):
            for key in list(data.keys()):
                if key in _SENTRY_REQUEST_DATA_FIELDS or key.endswith("_email"):
                    data[key] = ""
                    stripped_count += 1

        # Request headers — strip auth/cookie/ip headers
        headers = request.get("headers")
        if headers and isinstance(headers, dict):
            for header in _SENTRY_SENSITIVE_HEADERS:
                if header in headers and headers[header]:
                    headers[header] = ""
                    stripped_count += 1

        # Cookie string in env (Falcon/WSGI style)
        env = request.get("env")
        if env and isinstance(env, dict) and "COOKIE" in env:
            env["COOKIE"] = "[REDACTED]"
            stripped_count += 1

    # ------------------------------------------------------------------
    # 3. Extra data — email-like fields and JWT tokens
    # ------------------------------------------------------------------
    extra = event.get("extra")
    if extra and isinstance(extra, dict):
        for key in list(extra.keys()):
            if key.endswith("_email") or key == "email":
                extra[key] = ""
                stripped_count += 1
            # Catch JWT tokens (base64url-encoded JSON starting with eyJ)
            value = extra.get(key)
            if isinstance(value, str) and value.startswith("eyJ") and len(value) > 80:
                extra[key] = "[REDACTED JWT]"
                stripped_count += 1

    # ------------------------------------------------------------------
    # 4. Contexts — browser/OS data is fine, but user-supplied context
    #    with PII-pattern keys gets sanitized
    # ------------------------------------------------------------------
    contexts = event.get("contexts")
    if contexts and isinstance(contexts, dict):
        for ctx_key, ctx_val in contexts.items():
            if isinstance(ctx_val, dict):
                for field in _SENTRY_PII_FIELDS:
                    if field in ctx_val and ctx_val[field]:
                        ctx_val[field] = ""
                        stripped_count += 1

    # ------------------------------------------------------------------
    # 5. Tags — redact email-like tag values
    # ------------------------------------------------------------------
    tags = event.get("tags")
    if tags and isinstance(tags, dict):
        for key in list(tags.keys()):
            value = tags[key]
            if isinstance(value, str) and "@" in value and "." in value.split("@")[-1]:
                tags[key] = "[REDACTED EMAIL]"
                stripped_count += 1

    # ------------------------------------------------------------------
    # Log transparency count at DEBUG
    # ------------------------------------------------------------------
    if stripped_count:
        logger = logging.getLogger("science-ed.sentry")
        logger.debug("Sentry PII filter stripped %d field(s)", stripped_count)

    return event
