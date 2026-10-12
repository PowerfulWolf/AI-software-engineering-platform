"""Real isolated service stop -> local plan -> confirmed normal start wiring."""

from __future__ import annotations

import json
import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from ai_software_engineer.web_console.fault_retirement import (
    inspection_required,
    prepare_fault_retirement,
)
from ai_software_engineer.web_console.maintenance_names import NORMAL_ADMISSION_NAME
from tests.test_console_service_script import SCRIPT, _launcher
from tests.web_console.test_fault_retirement import _execute, _host


def _run(script: Path, env: dict[str, str], *arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(script), *arguments], env=env, capture_output=True, text=True, check=False, timeout=60
    )


@pytest.mark.parametrize("busy", [False, True])
def test_real_script_completion_or_busy_queue_stays_inspection(tmp_path: Path, busy: bool) -> None:
    with _host(tmp_path) as (retirement_env, _):
        old = prepare_fault_retirement(retirement_env)
        _execute(retirement_env, old.record_sha256)
        root = Path(retirement_env["ASE_SERVICE_STATE_DIR"])
        retained = {
            str(p.relative_to(root)): p.read_bytes()
            for p in (root / "console-fault-retirements").rglob("*")
            if p.is_file()
        }
        marker = (root / "console-inspection.json").read_bytes()
        script, env = _launcher(tmp_path)
        shutil.copy2(SCRIPT.with_name("ase-console-maintenance.py"), script.parent)
        # Only the isolated helper's SQL observer is replaced; launcher, lifecycle,
        # process absence, archive, confirmations and durable release gates are real.
        injection = tmp_path / "injection"
        injection.mkdir()
        (injection / "sitecustomize.py").write_text(
            "import os\n"
            "from ai_software_engineer.web_console import maintenance_completion as m\n"
            "from ai_software_engineer.web_console.maintenance_queue "
            "import MaintenanceQueueInventory\n"
            "def observe(*args):\n"
            "    return MaintenanceQueueInventory(inventory_sha256='a'*64, "
            "team_manifest_sha256='b'*64,\n"
            "        operation_count=0, work_item_count=1, claim_count=0, "
            "waiting_work_item_count=0,\n"
            "        blocked_work_item_ids=('work_busy_001',) "
            "if os.environ.get('ASE_TEST_COMPLETION_BUSY') else ())\n"
            "m.observe_maintenance_queue = observe\n"
        )
        env.update(retirement_env)
        interpreter = script.parent.parent / ".venv" / "bin" / "python"
        injected_path = str(injection) + os.pathsep + env["PYTHONPATH"]
        interpreter.write_text(
            f"#!/bin/sh\nPYTHONPATH={shlex.quote(injected_path)} "
            f'exec {shlex.quote(sys.executable)} "$@"\n'
        )
        service = interpreter.with_name("ase-console")
        service.write_text(
            service.read_text()
            .replace(
                "instance = instance.with_state(state, at=datetime.now(UTC))",
                "finished_at = datetime.now(UTC)\n"
                "        instance = instance.with_state(state, at=finished_at)",
            )
            .replace(
                "request, state=state, at=datetime.now(UTC)", "request, state=state, at=finished_at"
            )
        )
        if busy:
            env["ASE_TEST_COMPLETION_BUSY"] = "1"
        try:
            started = _run(script, env, "start")
            assert started.returncode == 0, started.stderr
            prepared = _run(script, env, "prepare-maintenance-completion")
            if busy:
                assert prepared.returncode == 1
                assert "队列" in prepared.stderr
                assert inspection_required(env)
                assert not (root / NORMAL_ADMISSION_NAME).exists()
                assert _run(script, env, "status").returncode == 0, (
                    prepared.stdout + prepared.stderr
                )
            else:
                assert prepared.returncode == 0, prepared.stderr
                plan = json.loads(prepared.stdout.splitlines()[-1])
                rejected = _run(script, env, "complete-maintenance", plan["record_sha256"])
                assert rejected.returncode != 0
                assert inspection_required(env)
                completed = _run(
                    script,
                    env,
                    "complete-maintenance",
                    plan["record_sha256"],
                    "--confirm-restore-normal",
                )
                assert completed.returncode == 0, completed.stderr
                assert not inspection_required(env)
                assert (root / NORMAL_ADMISSION_NAME).is_file()
                assert _run(script, env, "status").returncode == 0
            assert (root / "console-inspection.json").read_bytes() == marker
            for name, body in retained.items():
                assert (root / name).read_bytes() == body
        finally:
            _run(script, env, "stop")
