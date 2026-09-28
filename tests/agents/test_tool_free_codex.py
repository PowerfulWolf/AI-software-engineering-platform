"""Real CLI catalog probe: proposal-only models must have no execution tools."""

from __future__ import annotations

import json
import os
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest


@pytest.mark.skipif(
    not os.environ.get("ASE_TEST_CODEX_EXECUTABLE"), reason="explicit local CLI probe only"
)
@pytest.mark.parametrize("attack", ["none", "patch", "command", "image", "images12"])
def test_real_proposal_cli_has_no_execution_tools(tmp_path: Path, attack: str) -> None:
    from ai_software_engineer.agents.codex_policy import no_command_arguments
    from tests.domain.test_visual_evidence import png_evidence

    requests: list[dict[str, object]] = []
    image_args: tuple[str, ...] = ()
    if attack in {"image", "images12"}:
        for index in range(12 if attack == "images12" else 1):
            path = tmp_path / f"fixture-{index}.png"
            path.write_bytes(png_evidence().bytes())
            image_args += ("--image", str(path))

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: object) -> None:
            pass

        def do_POST(self) -> None:
            requests.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
            message = {
                "type": "message",
                "id": "msg_fixture",
                "role": "assistant",
                "status": "completed",
                "content": [{"type": "output_text", "text": '{"ok":true}'}],
            }
            response = {
                "id": "resp_fixture",
                "object": "response",
                "status": "completed",
                "output": [message],
                "usage": {"input_tokens": 1, "output_tokens": 1, "total_tokens": 2},
            }
            if attack == "patch" and len(requests) == 1:
                message = {
                    "type": "custom_tool_call",
                    "id": "ct_fixture",
                    "call_id": "call_fixture",
                    "name": "apply_patch",
                    "input": (
                        "*** Begin Patch\n*** Add File: forbidden.txt\n+forbidden\n*** End Patch"
                    ),
                }
                response["output"] = [message]
            elif attack == "command" and len(requests) == 1:
                message = {
                    "type": "function_call",
                    "id": "fc_fixture",
                    "call_id": "call_fixture",
                    "name": "exec_command",
                    "arguments": json.dumps({"cmd": "/usr/bin/touch forbidden.txt"}),
                }
                response["output"] = [message]
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            for event in (
                {"type": "response.output_item.done", "output_index": 0, "item": message},
                {"type": "response.completed", "response": response},
            ):
                self.wfile.write(("data: " + json.dumps(event) + "\n\n").encode())

    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        result = subprocess.run(
            (
                os.environ["ASE_TEST_CODEX_EXECUTABLE"],
                "exec",
                "--ephemeral",
                "--ignore-user-config",
                "--skip-git-repo-check",
                "--sandbox",
                "read-only",
                *image_args,
                *no_command_arguments(),
                "-c",
                'model_provider="ase_fixture"',
                "-c",
                'model_providers.ase_fixture.name="Fixture"',
                "-c",
                f'model_providers.ase_fixture.base_url="http://127.0.0.1:{server.server_port}/v1"',
                "-c",
                'model_providers.ase_fixture.wire_api="responses"',
                "-c",
                "model_providers.ase_fixture.requires_openai_auth=false",
                "-c",
                "features.enable_request_compression=false",
                "-m",
                "gpt-5.4",
                "-C",
                str(tmp_path),
                "-",
            ),
            input='Return exactly {"ok":true}; this is an offline fixture.',
            capture_output=True,
            text=True,
            timeout=40,
            check=False,
            env={
                key: os.environ[key] for key in ("PATH", "HOME", "CODEX_HOME") if key in os.environ
            },
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
    assert result.returncode == 0, result.stderr[-4000:]
    assert requests
    for payload in requests:
        catalog = payload.get("tools", [])
        assert isinstance(catalog, list)
        assert {item["name"] for item in catalog} <= {"request_user_input", "apply_patch"}
    assert not (tmp_path / "forbidden.txt").exists()
    if attack in {"image", "images12"}:
        inputs = requests[0]["input"]
        assert isinstance(inputs, list)
        images = [
            part
            for item in inputs
            if isinstance(item, dict)
            for part in item.get("content", [])
            if isinstance(part, dict) and part.get("type") == "input_image"
        ]
        assert len(images) == (12 if attack == "images12" else 1)
        assert all(item["image_url"] == png_evidence().data_url() for item in images)
    elif attack != "none":
        assert len(requests) == 2
        receipt = json.dumps(requests[-1]).lower()
        last_input = requests[-1]["input"]
        assert isinstance(last_input, list)
        outputs = [
            value
            for value in last_input
            if isinstance(value, dict) and value.get("type", "").endswith("_output")
        ]
        assert (
            "rejected" in receipt
            if attack == "patch"
            else any(
                word in str(outputs).lower() for word in ("unrecognized", "unknown", "unsupported")
            )
        ), outputs
