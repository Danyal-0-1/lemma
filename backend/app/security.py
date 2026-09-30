# ────────────────────────────────────────────────────────────────────────────
# security.py — local transport boundary shared by HTTP and WebSocket routes.
# READING ORDER: backend #4a
#
# Localhost binding alone does not stop a hostile webpage from driving a local API.
# This module therefore checks three independent facts: the peer is loopback, the Host
# header names loopback, and every browser-initiated mutation/socket has an exact trusted
# Origin. It is intentionally small; multi-user remote access needs real authentication.
# ─────────────────────────────────────────────────────────────────────────────

from __future__ import annotations

import ipaddress
from collections.abc import Iterable
from urllib.parse import urlsplit

from fastapi import WebSocket
from starlette.datastructures import Headers
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

_SAFE_HOSTS = frozenset({"127.0.0.1", "localhost", "::1", "testserver"})
_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
_SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Cache-Control": "no-store",
    "Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
}


def _hostname(host_header: str | None) -> str | None:
    """Extract a hostname from an HTTP Host header, including bracketed IPv6."""
    if not host_header:
        return None
    try:
        return urlsplit(f"//{host_header}").hostname
    except ValueError:
        return None


def is_safe_host(host_header: str | None) -> bool:
    """Return whether a Host header names one of the explicit loopback hosts."""
    return _hostname(host_header) in _SAFE_HOSTS


def is_loopback_client(scope: Scope) -> bool:
    """Return whether the ASGI peer address is loopback.

    Starlette's in-process TestClient uses the sentinel hostname ``testclient``; a real
    network server supplies a parsed IP address, so accepting the sentinel does not open
    a network path.
    """
    client = scope.get("client")
    if not client:
        return False
    host = client[0]
    if host == "testclient":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def is_allowed_origin(origin: str | None, allowed_origins: Iterable[str]) -> bool:
    """Return whether Origin exactly matches one configured browser origin."""
    if origin is None:
        return False
    return origin in frozenset(allowed_origins)


def websocket_is_trusted(websocket: WebSocket, allowed_origins: Iterable[str]) -> bool:
    """Validate peer, Host, and Origin before accepting a WebSocket."""
    return (
        is_loopback_client(websocket.scope)
        and is_safe_host(websocket.headers.get("host"))
        and is_allowed_origin(websocket.headers.get("origin"), allowed_origins)
    )


class LocalOnlyMiddleware:
    """Reject non-loopback HTTP traffic and cross-origin state-changing requests."""

    def __init__(self, app: ASGIApp, allowed_origins: list[str]) -> None:
        self.app = app
        self.allowed_origins = frozenset(allowed_origins)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = Headers(scope=scope)
        if not is_loopback_client(scope) or not is_safe_host(headers.get("host")):
            response = JSONResponse(
                {"detail": "local requests only"},
                status_code=403,
                headers=_SECURITY_HEADERS,
            )
            await response(scope, receive, send)
            return

        method = str(scope.get("method", "GET")).upper()
        if method not in _SAFE_METHODS and not is_allowed_origin(
            headers.get("origin"), self.allowed_origins
        ):
            response = JSONResponse(
                {"detail": "untrusted request origin"},
                status_code=403,
                headers=_SECURITY_HEADERS,
            )
            await response(scope, receive, send)
            return

        async def send_hardened(message: dict) -> None:
            """Attach conservative headers to every backend HTTP response."""
            if message.get("type") == "http.response.start":
                headers = list(message.get("headers", []))
                headers.extend(
                    [
                        (key.lower().encode(), value.encode())
                        for key, value in _SECURITY_HEADERS.items()
                    ]
                )
                message = {**message, "headers": headers}
            await send(message)

        await self.app(scope, receive, send_hardened)
