"""A private bounded Unix proxy to one owned network-none container's loopback."""

from __future__ import annotations

import os
import signal
import socket
import subprocess
import threading
import time
from contextlib import nullcontext, suppress
from pathlib import Path

from ai_software_engineer.manager.python_mysql_resources import IsolatedMysqlResource
from ai_software_engineer.owned_processes import (
    OwnedProcessesUncertain,
    current_owned_operation,
    finish_owned_process,
    observe_owned_process,
)

# Versioned trusted implementation, never interpolated SQL or model-provided shell.
MYSQL_RELAY = (
    "exec 3<>/dev/tcp/127.0.0.1/3306; cat <&3 & peer=$!; "
    'cat >&3; kill "$peer" 2>/dev/null; wait "$peer" 2>/dev/null; exit 0'
)


class MysqlUnixProxy:
    def __init__(self, resource: IsolatedMysqlResource, endpoint: Path) -> None:
        if resource.container_id is None or endpoint.name != "mysql.sock":
            raise ValueError("proxy requires the exact created resource and socket")
        self._resource, self._endpoint = resource, endpoint
        self._owned_operation = current_owned_operation()
        self._cleanup_uncertain = threading.Event()
        self._stop = threading.Event()
        self._slots = threading.BoundedSemaphore(32)
        self._lock = threading.Lock()
        self._clients: set[socket.socket] = set()
        self._processes: set[subprocess.Popen[bytes]] = set()
        self._workers: list[threading.Thread] = []
        self._server = socket.socket(socket.AF_UNIX)
        self._server.bind(str(endpoint))
        os.chmod(endpoint, 0o600)
        self._server.listen(32)
        self._server.settimeout(0.2)
        self._thread = threading.Thread(target=self._accept, daemon=True)
        self._thread.start()

    def _accept(self) -> None:
        accepted = 0
        while not self._stop.is_set() and accepted < 4096:
            try:
                client, _ = self._server.accept()
            except TimeoutError:
                continue
            except OSError:
                break
            accepted += 1
            if not self._slots.acquire(blocking=False):
                client.close()
                continue
            with self._lock:
                self._clients.add(client)
            worker = threading.Thread(target=self._bridge, args=(client,), daemon=True)
            self._workers.append(worker)
            worker.start()

    def _bridge(self, client: socket.socket) -> None:
        with self._owned_operation.activate() if self._owned_operation else nullcontext():
            self._bridge_owned(client)

    def _bridge_owned(self, client: socket.socket) -> None:
        process: subprocess.Popen[bytes] | None = None
        upstream: threading.Thread | None = None
        observation = None
        try:
            process = subprocess.Popen(
                (
                    *self._resource.docker_prefix,
                    "exec",
                    "-i",
                    self._resource.container_id or "",
                    "/usr/bin/bash",
                    "-c",
                    MYSQL_RELAY,
                ),
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                env={"PATH": "/usr/bin:/bin", "LANG": "C", "LC_ALL": "C"},
                start_new_session=True,
            )
            observation = observe_owned_process(process, kind="tool")
            assert process.stdin is not None and process.stdout is not None
            with self._lock:
                self._processes.add(process)
            current = process

            def write_upstream() -> None:
                assert current.stdin is not None
                try:
                    while not self._stop.is_set():
                        data = client.recv(65_536)
                        if not data:
                            break
                        current.stdin.write(data)
                        current.stdin.flush()
                except (OSError, ValueError):
                    pass
                finally:
                    with suppress(OSError, ValueError):
                        current.stdin.close()

            upstream = threading.Thread(target=write_upstream, daemon=True)
            upstream.start()
            while not self._stop.is_set():
                data = os.read(process.stdout.fileno(), 65_536)
                if not data:
                    break
                client.sendall(data)
        except (OSError, ValueError):
            pass
        finally:
            with suppress(OSError):
                client.shutdown(socket.SHUT_RDWR)
            client.close()
            if process is not None:
                try:
                    finish_owned_process(process, None, output_drained=False)
                    if upstream is not None:
                        upstream.join(timeout=1)
                        if upstream.is_alive():
                            raise OwnedProcessesUncertain("MySQL proxy pipe worker did not stop")
                    if observation is not None:
                        observation.stopped(output_drained=True)
                    if process.stdout is not None:
                        process.stdout.close()
                    if process.stdin is not None:
                        with suppress(OSError, ValueError):
                            process.stdin.close()
                except OwnedProcessesUncertain:
                    self._cleanup_uncertain.set()
                    if observation is not None:
                        observation.uncertain()
                with self._lock:
                    self._processes.discard(process)
            if upstream is not None:
                upstream.join(timeout=5)
            with self._lock:
                self._clients.discard(client)
            self._slots.release()

    def close(self) -> None:
        deadline = time.monotonic() + 5
        self._stop.set()
        self._server.close()
        with self._lock:
            for client in self._clients:
                with suppress(OSError):
                    client.shutdown(socket.SHUT_RDWR)
            for process in self._processes:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                except PermissionError:
                    # A reaped-zombie race is not proof either way. The bridge
                    # still must independently verify its owned group and pipe.
                    pass
                except OSError:
                    self._cleanup_uncertain.set()
        self._thread.join(timeout=max(0, deadline - time.monotonic()))
        for worker in self._workers:
            worker.join(timeout=max(0, deadline - time.monotonic()))
        if self._thread.is_alive() or any(worker.is_alive() for worker in self._workers):
            raise RuntimeError("MySQL proxy did not terminate within its cleanup bound")
        if self._cleanup_uncertain.is_set():
            raise OwnedProcessesUncertain("MySQL proxy owned execution stop remains unknown")
