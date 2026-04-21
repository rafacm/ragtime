"""ASGI config for the ragtime project.

Exposes two ASGI apps behind a path-based dispatcher:

- ``/chat/agent/`` — Scott's Pydantic AI agent (AG-UI HTTP+SSE protocol),
  wrapped in a lightweight auth middleware that validates the Django
  session cookie and rejects unauthenticated callers with 401.
- everything else — the regular Django ASGI application.
"""

from __future__ import annotations

import os
from http import cookies

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "ragtime.settings")

from django.conf import settings  # noqa: E402
from django.core.asgi import get_asgi_application  # noqa: E402

_django_app = get_asgi_application()

if settings.DEBUG:
    from django.contrib.staticfiles.handlers import ASGIStaticFilesHandler

    _django_app = ASGIStaticFilesHandler(_django_app)


async def _send_unauthorized(send) -> None:
    await send(
        {
            "type": "http.response.start",
            "status": 401,
            "headers": [(b"content-type", b"application/json")],
        }
    )
    await send(
        {
            "type": "http.response.body",
            "body": b'{"error":"authentication required"}',
        }
    )


def _extract_cookie_value(scope, name: str) -> str | None:
    for header_name, header_value in scope.get("headers") or []:
        if header_name == b"cookie":
            jar = cookies.SimpleCookie()
            try:
                jar.load(header_value.decode("latin-1"))
            except cookies.CookieError:
                return None
            morsel = jar.get(name)
            return morsel.value if morsel else None
    return None


async def _session_is_authenticated(session_key: str) -> bool:
    """Return True iff the session identifies a valid, active user."""
    from django.contrib.auth import BACKEND_SESSION_KEY, SESSION_KEY, get_user_model
    from django.contrib.sessions.backends.db import SessionStore

    store = SessionStore(session_key=session_key)

    def _load() -> dict | None:
        try:
            data = store.load()
        except Exception:
            return None
        return data or None

    import asyncio

    data = await asyncio.to_thread(_load)
    if not data:
        return False

    user_id = data.get(SESSION_KEY)
    backend_path = data.get(BACKEND_SESSION_KEY)
    if user_id is None or backend_path is None:
        return False

    User = get_user_model()
    try:
        user = await User.objects.aget(pk=user_id)
    except User.DoesNotExist:
        return False
    return bool(user.is_active)


def _agui_app():
    """Lazy accessor so settings are loaded before the agent is built."""
    from chat.agent import get_agui_app

    return get_agui_app()


AGUI_PREFIX = "/chat/agent"


def _substitute_prefix(scope, prefix):
    """Return a new scope with ``prefix`` stripped from ``path`` (standard
    ASGI sub-mount pattern). Leaves the original ``scope`` untouched."""
    path = scope.get("path", "")
    new_path = path[len(prefix):] or "/"
    new_scope = dict(scope)
    new_scope["path"] = new_path
    new_scope["root_path"] = scope.get("root_path", "") + prefix
    return new_scope


async def _authenticated_agui(scope, receive, send):
    if scope["type"] != "http":
        await _send_unauthorized(send)
        return

    cookie_name = settings.SESSION_COOKIE_NAME
    session_key = _extract_cookie_value(scope, cookie_name)
    if not session_key or not await _session_is_authenticated(session_key):
        await _send_unauthorized(send)
        return

    await _agui_app()(_substitute_prefix(scope, AGUI_PREFIX), receive, send)


async def application(scope, receive, send):
    path = scope.get("path", "") if scope.get("type") in {"http", "websocket"} else ""
    if path == AGUI_PREFIX or path.startswith(AGUI_PREFIX + "/"):
        await _authenticated_agui(scope, receive, send)
        return
    await _django_app(scope, receive, send)
