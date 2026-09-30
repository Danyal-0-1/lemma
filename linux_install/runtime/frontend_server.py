#!/usr/bin/env python3
"""Serve Lemma's production frontend on loopback with strict response headers.

This intentionally uses only the Python standard library.  It is not a general
purpose file server: the document root is fixed at startup, dot files are denied,
directory listings are disabled, and unknown client-side routes fall back to the
bundled ``index.html``.
"""

from __future__ import annotations

import argparse
import mimetypes
import posixpath
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlsplit


SECURITY_HEADERS = {
    "Cache-Control": "no-store",
    "Content-Security-Policy": "; ".join(
        [
            "default-src 'self'",
            "base-uri 'none'",
            (
                "connect-src 'self' http://127.0.0.1:8000 "
                "http://localhost:8000 ws://127.0.0.1:8000 "
                "ws://localhost:8000"
            ),
            "font-src 'self' data:",
            "form-action 'none'",
            "frame-ancestors 'none'",
            "img-src 'self' data: blob:",
            "object-src 'none'",
            "script-src 'self'",
            "style-src 'self' 'unsafe-inline'",
            "worker-src 'self' blob:",
        ]
    ),
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
    "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
}

class LemmaHandler(BaseHTTPRequestHandler):
    """A bounded static handler with SPA fallback and no directory indexes."""

    server_version = "LemmaFrontend"
    sys_version = ""
    root: Path
    allowed_hosts = {"127.0.0.1:5173", "localhost:5173"}

    def _host_is_allowed(self) -> bool:
        """Accept only the two loopback authorities the launcher advertises."""
        values = self.headers.get_all("Host", failobj=[])
        return len(values) == 1 and values[0].strip().lower() in self.allowed_hosts

    def _reject_untrusted_host(self) -> bool:
        """Reject DNS-rebinding and malformed requests before resolving a path."""
        if self._host_is_allowed():
            return False
        self.send_error(HTTPStatus.MISDIRECTED_REQUEST, "Untrusted Host header")
        return True

    def _candidate(self) -> Path | None:
        try:
            raw_path = unquote(urlsplit(self.path).path, errors="strict")
        except (UnicodeDecodeError, ValueError):
            return None
        if any(ord(character) < 32 or ord(character) == 127 for character in raw_path):
            return None
        normalized = posixpath.normpath(raw_path)
        parts = [part for part in normalized.split("/") if part]
        if any(part in {".", ".."} or part.startswith(".") for part in parts):
            return None
        candidate = self.root.joinpath(*parts).resolve(strict=False)
        if not candidate.is_relative_to(self.root):
            return None
        if candidate.is_file():
            return candidate
        # Vite is a client-side SPA. Extensionless routes get its entry point;
        # missing asset requests stay 404 so mistakes are visible.
        if not parts or "." not in parts[-1]:
            return self.root / "index.html"
        return None

    def _serve(self, *, send_body: bool) -> None:
        if self._reject_untrusted_host():
            return
        candidate = self._candidate()
        if candidate is None or not candidate.is_file():
            self.send_error(HTTPStatus.NOT_FOUND, "Not found")
            return
        try:
            size = candidate.stat().st_size
            content_type = mimetypes.guess_type(candidate.name)[0] or "application/octet-stream"
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(size))
            self.end_headers()
            if send_body:
                with candidate.open("rb") as source:
                    while chunk := source.read(128 * 1024):
                        self.wfile.write(chunk)
        except (BrokenPipeError, ConnectionResetError):
            return
        except OSError:
            self.send_error(HTTPStatus.INTERNAL_SERVER_ERROR, "Unable to read asset")

    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        self._serve(send_body=True)

    def do_HEAD(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        self._serve(send_body=False)

    def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        if self._reject_untrusted_host():
            return
        self.send_error(HTTPStatus.METHOD_NOT_ALLOWED, "Method not allowed")

    def list_directory(self, _path: str):  # type: ignore[no-untyped-def]
        self.send_error(HTTPStatus.FORBIDDEN, "Directory listing disabled")
        return None

    def log_message(self, format_string: str, *args: object) -> None:
        # Keep one concise line in the user service log; never include headers.
        print(f"frontend: {self.address_string()} {format_string % args}", flush=True)

    def end_headers(self) -> None:
        # Centralizing the headers here also hardens errors generated by send_error().
        for key, value in SECURITY_HEADERS.items():
            self.send_header(key, value)
        super().end_headers()


def main() -> None:
    parser = argparse.ArgumentParser(description="Serve the Lemma frontend on loopback")
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--port", type=int, default=5173)
    args = parser.parse_args()

    root = args.root.resolve(strict=True)
    if not root.is_dir() or not (root / "index.html").is_file():
        raise SystemExit("frontend root is missing index.html")
    if not 1024 <= args.port <= 65535:
        raise SystemExit("port must be between 1024 and 65535")

    LemmaHandler.root = root
    LemmaHandler.allowed_hosts = {
        f"127.0.0.1:{args.port}",
        f"localhost:{args.port}",
    }
    server = ThreadingHTTPServer(("127.0.0.1", args.port), LemmaHandler)
    server.daemon_threads = True
    print(f"Lemma frontend listening on http://127.0.0.1:{args.port}", flush=True)
    try:
        server.serve_forever(poll_interval=0.5)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
