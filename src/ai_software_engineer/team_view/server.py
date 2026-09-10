"""Loopback-only HTTP transport; no file browsing or write routes."""

from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib.resources import files
from threading import Lock
from typing import Protocol
from urllib.parse import unquote

from .models import TeamSnapshot


class TeamReader(Protocol):
    def snapshot(self, company_id: str | None = None) -> TeamSnapshot: ...


def create_team_server(reader: TeamReader, *, port: int = 8765) -> ThreadingHTTPServer:
    if isinstance(port, bool) or not 0 <= port <= 65535:
        raise ValueError("invalid team server port")
    assets = {
        "/": ("index.html", "text/html; charset=utf-8"),
        "/app.js": ("app.js", "text/javascript; charset=utf-8"),
        "/style.css": ("style.css", "text/css; charset=utf-8"),
    }
    gate = Lock()

    class Handler(BaseHTTPRequestHandler):
        def setup(self) -> None:
            super().setup()
            self.connection.settimeout(10)

        def log_message(self, format: str, *args: object) -> None:
            pass  # never log untrusted URL/header strings or response facts

        def _allowed(self) -> bool:
            expected = f"127.0.0.1:{server.server_port}"
            hosts = self.headers.get_all("Host", [])
            origins = self.headers.get_all("Origin", [])
            return hosts == [expected] and (not origins or origins == [f"http://{expected}"])

        def _send(self, status: int, body: bytes, content_type: str) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Cross-Origin-Resource-Policy", "same-origin")
            self.send_header(
                "Content-Security-Policy",
                (
                    "default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; "
                    "base-uri 'none'; frame-ancestors 'none'; form-action 'none'"
                ),
            )
            if status == 405:
                self.send_header("Allow", "GET")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:
            if not self._allowed():
                self._send(403, b'{"error":"Forbidden origin or host"}', "application/json")
                return
            if self.path in assets:
                name, content_type = assets[self.path]
                self._send(200, files(__package__).joinpath(name).read_bytes(), content_type)
                return
            company_id: str | None = None
            if self.path.startswith("/api/v1/team/"):
                company_id = unquote(self.path.removeprefix("/api/v1/team/"))
                if not company_id or "/" in company_id or "?" in company_id:
                    self._send(404, b'{"error":"Not found"}', "application/json")
                    return
            elif self.path != "/api/v1/team":
                self._send(404, b'{"error":"Not found"}', "application/json")
                return
            if not gate.acquire(blocking=False):
                self._send(503, b'{"error":"Read in progress"}', "application/json")
                return
            try:
                try:
                    snapshot = reader.snapshot(company_id)
                    body = snapshot.model_dump_json().encode("utf-8")
                except Exception:
                    self._send(503, b'{"error":"Team data unavailable"}', "application/json")
                    return
                self._send(200, body, "application/json; charset=utf-8")
            finally:
                gate.release()

        def _deny_write(self) -> None:
            self._send(405, b'{"error":"Read-only API"}', "application/json")

        do_POST = do_PUT = do_PATCH = do_DELETE = do_OPTIONS = do_HEAD = _deny_write

    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    return server
