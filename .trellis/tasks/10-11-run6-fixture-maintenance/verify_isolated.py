"""Verify the exact frozen correction in a disposable local clone, never production."""

from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

from fixture_correction import (
    FILES,
    TARGET,
    TASK_ID,
    MaintenancePlan,
    build_plan,
    corrected_source,
    queue_from_config,
    read_facts,
    read_regular,
    require,
    seal,
    sha256,
)

from ai_software_engineer.git import GitWorktreeManager
from ai_software_engineer.git.mutation import capture_mutation_inventory, changed_mutation_paths
from ai_software_engineer.git.ports import WorktreeSpec
from ai_software_engineer.git.worktree import WorktreeCaptureRejected
from ai_software_engineer.orchestration.continuation_capture import CapturedMutations
from ai_software_engineer.recovery.models import canonical_bytes
from ai_software_engineer.redaction import redact_text, source_secret_occurrences


def main() -> None:
    plan = MaintenancePlan.model_validate_json((FILES / "plan.json").read_bytes())
    plan.validate_integrity()
    with read_facts(queue_from_config()) as facts:
        require(build_plan(facts, plan.created_at) == plan)
        production = Path(facts.start.worktree_path)
        source_manager = GitWorktreeManager(
            facts.task.repository,
            production.parent.parent,
            branch_names={TASK_ID: facts.task.branch_name},
        )
        spec = WorktreeSpec(
            task_id=TASK_ID,
            role=facts.start.request.role,
            attempt=1,
            source_revision=facts.start.request.source_revision,
        )
        source = source_manager.recover(spec)
        paths = source_manager.inspect(source).changed_paths
        require(TARGET in paths)
        require(not source_manager._run_git(("diff", "--cached", "--binary"), cwd=production))
        inventory = {item.path: item for item in facts.inventory.files}
        bodies = {
            path: (
                read_regular(production / path, maximum=16_000_000),
                inventory[path].mode,
            )
            if path in inventory
            else None
            for path in paths
        }
        require(
            all(
                item is None or sha256(item[0]) == inventory[path].sha256
                for path, item in bodies.items()
            )
        )

    with TemporaryDirectory(prefix="ase-run6-maintenance-") as temporary:
        root = Path(temporary).resolve()
        repository = root / "repository"
        environment = {
            key: os.environ[key] for key in ("PATH", "LANG", "LC_ALL") if key in os.environ
        }
        subprocess.run(
            (
                "git",
                "clone",
                "--shared",
                "--no-checkout",
                "--",
                facts.task.repository,
                str(repository),
            ),
            env=environment,
            capture_output=True,
            check=True,
            timeout=60,
        )
        manager = GitWorktreeManager(
            repository, root / "worktrees", branch_names={TASK_ID: facts.task.branch_name}
        )
        worktree = manager.create(spec)
        for path, body in bodies.items():
            destination = worktree.path / path
            if body is None:
                destination.unlink()
            else:
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(body[0])
                destination.chmod(body[1])
        require(manager.inspect(worktree).changed_paths == paths)
        denied = facts.task.constraints.denied_paths if facts.task.constraints else ()
        before = capture_mutation_inventory(worktree.path)
        index_path = Path(
            manager._run_git(
                ("rev-parse", "--path-format=absolute", "--git-path", "index"), cwd=worktree.path
            )
        )
        index_before = sha256(read_regular(index_path, maximum=16_000_000))
        original = (worktree.path / TARGET).read_bytes()
        require(sha256(original) == plan.before_sha256)
        require(len(source_secret_occurrences(original.decode(), source_path=TARGET)) == 1)
        try:
            manager.capture_mutations(
                worktree, facts.start.request.permissions, denied_paths=denied
            )
        except WorktreeCaptureRejected:
            rejected = True
        else:
            rejected = False
        require(rejected)
        corrected = corrected_source(original)
        (worktree.path / TARGET).write_bytes(corrected)
        require(stat.S_IMODE((worktree.path / TARGET).stat().st_mode) == plan.mode)
        after = capture_mutation_inventory(worktree.path)
        require(changed_mutation_paths(before, after) == (TARGET,))
        captured = manager.capture_mutations(
            worktree, facts.start.request.permissions, denied_paths=denied
        )
        stored = CapturedMutations.from_capture(captured)
        require(CapturedMutations.model_validate(stored.to_wire()).to_capture() == captured)
        manager.verify_mutations(captured, facts.start.request.permissions, denied_paths=denied)
        require(captured.changed_paths == paths)
        require(manager.recover(spec) == worktree)
        require(sha256(read_regular(index_path, maximum=16_000_000)) == index_before)
        require(capture_mutation_inventory(worktree.path) == after)

        # The concurrency test intentionally drops ambient PYTHONPATH. Supply an
        # external source-bound launcher so its subprocesses exercise this clone.
        launcher = root / "source-python"
        launcher.write_text(
            f"#!{sys.executable}\n"
            "import os, pathlib, sys\n"
            f"root = pathlib.Path({str(worktree.path)!r})\n"
            "assert pathlib.Path.cwd() == root\n"
            "env = {k: os.environ[k] for k in ('PATH', 'LANG', 'LC_ALL') if k in os.environ}\n"
            "env['PYTHONPATH'] = str(root / 'src') + os.pathsep + str(root)\n"
            "env['PYTHONDONTWRITEBYTECODE'] = '1'\n"
            "os.execve(sys.executable, [sys.executable, '-B', *sys.argv[1:]], env)\n"
        )
        launcher.chmod(0o700)
        test_environment = {
            **environment,
            "PYTHONPATH": str(worktree.path / "src") + os.pathsep + str(worktree.path),
            "PYTHONDONTWRITEBYTECODE": "1",
            "ASE_PROJECT_PYTHON": str(launcher),
        }
        node = TARGET + (
            "::TestK1BoundsRetry::"
            "test_ac_004_003_security_failure_cannot_release_unknown_or_stale_fence"
        )
        tests = []
        for selection in (node, TARGET):
            result = subprocess.run(
                (sys.executable, "-B", "-m", "pytest", "-q", "-p", "no:cacheprovider", selection),
                cwd=worktree.path,
                env=test_environment,
                capture_output=True,
                text=True,
                timeout=60,
            )
            summary = redact_text(result.stdout + result.stderr).text.strip()
            print(
                json.dumps(
                    {"selection": selection, "returncode": result.returncode, "summary": summary}
                )
            )
            require(result.returncode == 0 and "skipped" not in summary)
            tests.append(
                {"selection": selection, "returncode": result.returncode, "summary": summary}
            )
        require(capture_mutation_inventory(worktree.path) == after)
        verification = {
            "plan_sha256": plan.plan_sha256,
            "production_written": False,
            "isolated_before_capture": "WorktreeCaptureRejected",
            "isolated_after_capture": "accepted",
            "captured_paths": len(paths),
            "captured_mutation_sha256": captured.capture_sha256,
            "captured_patch_sha256": sha256(captured.patch),
            "captured_patch_bytes": len(captured.patch),
            "full_wire_roundtrip": True,
            "full_capture_verify": True,
            "only_correction_path_changed": TARGET,
            "head_branch_index_unchanged": True,
            "tests": tests,
        }
    with read_facts(queue_from_config()) as unchanged:
        require(build_plan(unchanged, plan.created_at) == plan)
    seal(FILES / "verification.json", canonical_bytes(verification) + b"\n")
    print(json.dumps({"verification": "passed", "production_written": False}))


if __name__ == "__main__":
    main()
