"""A real loopback HTTP body cannot keep renewing a provider socket timeout."""

from __future__ import annotations

import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from ai_software_engineer.agents.openai_compatible import UrllibHttpTransport


@contextmanager
def _server(*, drip: bool = False) -> Iterator[tuple[str, threading.Event]]:
    stopped = threading.Event()

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            self.rfile.read(int(self.headers.get("Content-Length", "0")))
            if self.path == "/redirect":
                self.send_response(302)
                self.send_header("Location", "/followed")
                self.send_header("Content-Length", "0")
                self.end_headers()
                stopped.set()
                return
            if self.path == "/followed":
                raise AssertionError("provider credential endpoint was redirected")
            if self.path == "/headers":
                try:
                    for byte in b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\n{}":
                        self.wfile.write(bytes((byte,)))
                        self.wfile.flush()
                        time.sleep(0.055)
                except (BrokenPipeError, ConnectionResetError):
                    pass
                finally:
                    stopped.set()
                return
            payload = (
                b'{"error":{"message":"unavailable"}}'
                if self.path == "/error"
                else b'{"value":"bounded"}'
            )
            self.send_response(503 if self.path == "/error" else 200)
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("x-request-id", "request-bounded")
            self.send_header("x-correlation-id", "correlation-bounded")
            self.end_headers()
            try:
                if drip:
                    for byte in payload:
                        self.wfile.write(bytes((byte,)))
                        self.wfile.flush()
                        time.sleep(0.055)
                else:
                    self.wfile.write(payload)
            except (BrokenPipeError, ConnectionResetError):
                pass
            finally:
                stopped.set()

        def log_message(self, format: str, *args: object) -> None:
            del format, args

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.daemon_threads = True
    thread = threading.Thread(target=lambda: server.serve_forever(poll_interval=0.01))
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", stopped
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=1)
        assert not thread.is_alive()


@pytest.mark.parametrize("path", ["/success", "/error", "/headers"])
def test_real_success_and_http_error_body_drips_stop_at_total_deadline(path: str) -> None:
    with _server(drip=True) as (endpoint, stopped):
        started = time.monotonic()
        with pytest.raises(TimeoutError):
            UrllibHttpTransport().post(
                endpoint + path, {"Content-Type": "application/json"}, b"{}", 0.25
            )
        elapsed = time.monotonic() - started
        # Each byte arrives before the original inactivity timeout; the old read()
        # required roughly 1 second or more, while the absolute window ends early.
        assert 0.18 <= elapsed < 0.7
        assert stopped.wait(timeout=1)


@pytest.mark.parametrize("path, status", [("/success", 200), ("/error", 503)])
def test_bounded_standard_http_response_and_diagnostic_headers_remain_compatible(
    path: str,
    status: int,
) -> None:
    with _server() as (endpoint, _):
        result = UrllibHttpTransport().post(endpoint + path, {}, b"{}", 1)
    assert result.status_code == status
    assert result.request_id == "request-bounded"
    assert result.correlation_id == "correlation-bounded"
    assert result.body.startswith(b"{")


def test_body_limit_is_enforced_for_success_and_error_without_changing_error_status() -> None:
    with _server() as (endpoint, _):
        with pytest.raises(OSError, match="configured limit"):
            UrllibHttpTransport(max_response_bytes=3).post(endpoint + "/success", {}, b"{}", 1)
        result = UrllibHttpTransport(max_response_bytes=3).post(endpoint + "/error", {}, b"{}", 1)
    assert result.status_code == 503 and result.body == b""


def test_model_endpoint_redirect_cannot_change_method_or_forward_bearer_authority() -> None:
    with _server() as (endpoint, _):
        result = UrllibHttpTransport().post(
            endpoint + "/redirect",
            {
                "Authorization": "Bearer fixture-secret",
            },
            b"{}",
            1,
        )
    assert result.status_code == 302 and result.body == b""


@pytest.mark.parametrize("timeout", [0, -1, float("inf"), float("nan")])
def test_invalid_window_is_rejected_before_opening_network(timeout: float) -> None:
    with pytest.raises(ValueError, match="finite positive"):
        UrllibHttpTransport().post("https://example.invalid", {}, b"{}", timeout)
