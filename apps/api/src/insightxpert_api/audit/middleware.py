"""FastAPI middleware — enqueues an AuditRow per mutating request.

Skips GET/HEAD/OPTIONS (non-mutating). Decodes the session cookie to derive
user_id when possible. Path → (resource_type, resource_id) mapping via regex
table. Never raises; every failure is logged and swallowed.
"""

from __future__ import annotations

import re
from typing import Awaitable, Callable

from typing import Callable

from fastapi import FastAPI, Request

from ..auth.session import SessionSigner
from ..config import get_settings
from ..logging import get_logger
from .queue import AuditRow, get_queue

log = get_logger("audit")

_SKIP_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})

# Ordered — first match wins. Patterns are anchored at the start of the path.
_RESOURCE_TABLE: list[tuple[re.Pattern[str], str, Callable[[re.Match[str]], str | None]]] = [
    (re.compile(r"^/api/v1/auth/login/?$"), "auth.session", lambda _m: None),
    (re.compile(r"^/api/v1/auth/logout/?$"), "auth.session", lambda _m: None),
    (re.compile(r"^/api/v1/auth/change-password/?$"), "auth.password", lambda _m: None),
    (re.compile(r"^/api/v1/auth/revoke-sessions/?$"), "auth.session", lambda _m: None),
    (re.compile(r"^/api/v1/admin/users/([^/]+)/?$"), "user", lambda m: m.group(1)),
    (re.compile(r"^/api/v1/admin/users/?$"), "user", lambda _m: None),
    # Database profile routes — must precede the generic /databases/(db_id) catch-all
    # so override mutations are tagged with the more specific resource type.
    (
        re.compile(
            r"^/api/v1/databases/([^/]+)/profile/columns/([^/]+)/([^/]+)/overrides/([^/]+)/?$"
        ),
        "database.profile",
        lambda m: m.group(1),
    ),
    (
        re.compile(
            r"^/api/v1/databases/([^/]+)/profile/columns/([^/]+)/([^/]+)/?$"
        ),
        "database.profile",
        lambda m: m.group(1),
    ),
    (
        re.compile(
            r"^/api/v1/databases/([^/]+)/profile/overrides/?$"
        ),
        "database.profile",
        lambda m: m.group(1),
    ),
    (
        re.compile(r"^/api/v1/databases/([^/]+)/profile/?$"),
        "database.profile",
        lambda m: m.group(1),
    ),
    (re.compile(r"^/api/v1/databases/([^/]+)/?$"), "database", lambda m: m.group(1)),
    (re.compile(r"^/api/v1/databases/?$"), "database", lambda _m: None),
    (re.compile(r"^/api/v1/conversations/([^/]+)/?$"), "conversation", lambda m: m.group(1)),
    (re.compile(r"^/api/v1/conversations/?$"), "conversation", lambda _m: None),
    (re.compile(r"^/api/v1/chat(?:/.*)?$"), "chat", lambda _m: None),
    (re.compile(r"^/api/v1/feedback/?$"), "feedback", lambda _m: None),
    (re.compile(r"^/api/v1/sql(?:/.*)?$"), "sql", lambda _m: None),
    # Automations — order matters: most specific first, generic last.
    (
        re.compile(r"^/api/v1/automations/templates/([^/]+)/?$"),
        "automation.template",
        lambda m: m.group(1),
    ),
    (
        re.compile(r"^/api/v1/automations/templates/?$"),
        "automation.template",
        lambda _m: None,
    ),
    (
        re.compile(r"^/api/v1/automations/compile-trigger/?$"),
        "automation.compile_trigger",
        lambda _m: None,
    ),
    (
        re.compile(r"^/api/v1/automations/generate-sql/?$"),
        "automation.generate_sql",
        lambda _m: None,
    ),
    (
        re.compile(r"^/api/v1/automations/([^/]+)/runs(?:/[^/]+)?/?$"),
        "automation.run",
        lambda m: m.group(1),
    ),
    (
        re.compile(r"^/api/v1/automations/([^/]+)/toggle/?$"),
        "automation",
        lambda m: m.group(1),
    ),
    (
        re.compile(r"^/api/v1/automations/([^/]+)/?$"),
        "automation",
        lambda m: m.group(1),
    ),
    (
        re.compile(r"^/api/v1/automations/?$"),
        "automation",
        lambda _m: None,
    ),
    # Notifications.
    (
        re.compile(r"^/api/v1/notifications/([^/]+)/read/?$"),
        "notification",
        lambda m: m.group(1),
    ),
    (
        re.compile(r"^/api/v1/notifications(?:/.*)?$"),
        "notification",
        lambda _m: None,
    ),
]


def _classify(path: str) -> tuple[str | None, str | None]:
    for pattern, rtype, extract in _RESOURCE_TABLE:
        m = pattern.match(path)
        if m:
            try:
                return rtype, extract(m)
            except Exception:  # noqa: BLE001
                return rtype, None
    return None, None


def _user_id_from_cookie(request: Request) -> str | None:
    try:
        settings = get_settings()
        token = request.cookies.get(settings.session_cookie_name)
        if not token:
            auth = request.headers.get("authorization", "")
            if auth.lower().startswith("bearer "):
                token = auth[7:].strip() or None
        if not token:
            return None
        claims = SessionSigner(settings).verify(token)
        return claims.user_id if claims is not None else None
    except Exception:  # noqa: BLE001
        return None


class AuditMiddleware:
    def __init__(self, app: Callable) -> None:
        self.app = app

    async def __call__(self, scope: dict, receive: Callable, send: Callable) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request = Request(scope, receive=receive)
        method = request.method.upper()
        if method in _SKIP_METHODS:
            await self.app(scope, receive, send)
            return

        status_code: int | None = None

        async def _send(message: dict) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message.get("status", 0)
            await send(message)

        try:
            await self.app(scope, receive, _send)
        except Exception:
            status_code = status_code or 500
            raise
        finally:
            try:
                path = request.url.path
                resource_type, resource_id = _classify(path)
                user_id = _user_id_from_cookie(request)
                ip = request.client.host if request.client else None
                ua = request.headers.get("user-agent")
                
                sc = status_code if status_code is not None else 500

                row = AuditRow(
                    user_id=user_id,
                    method=method,
                    path=path,
                    resource_type=resource_type,
                    resource_id=resource_id,
                    status_code=sc,
                    ip=ip,
                    user_agent=ua,
                )
                await get_queue().put(row)
            except Exception as exc:  # noqa: BLE001 — never fail the user request
                log.error(
                    "audit.middleware_failed",
                    error=str(exc),
                    error_type=type(exc).__name__,
                )


def register(app: FastAPI) -> None:
    app.add_middleware(AuditMiddleware)
