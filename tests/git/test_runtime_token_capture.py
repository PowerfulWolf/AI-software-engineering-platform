"""Real Git BEFORE bodies retain runtime handles without changing bytes or facts."""

import hashlib
from pathlib import Path

import pytest

from ai_software_engineer.domain import AgentPermissions, AgentRole, NetworkAccess
from ai_software_engineer.git import GitWorktreeManager, WorktreeCaptureRejected, WorktreeSpec
from ai_software_engineer.orchestration.continuation_capture import CapturedMutations
from tests.git.test_capture import git


@pytest.mark.parametrize("relative", ["knowledge/index.py", "web_console/transport.py"])
@pytest.mark.parametrize("unsafe", [False, True], ids=["runtime-handle", "other-secret-refused"])
def test_actual_platform_before_body_is_complete_and_capture_stays_read_only(
    tmp_path: Path, relative: str, unsafe: bool
) -> None:
    package = Path(__file__).parents[2] / "src/ai_software_engineer"
    before = (package / relative).read_text() + "\nCAPTURE_VALUE = 1\n"
    if unsafe:
        before += 'other = "password=must-remain-sensitive"\n'
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "--initial-branch=main")
    git(repo, "config", "user.name", "Fixture")
    git(repo, "config", "user.email", "fixture@example.invalid")
    (repo / "src").mkdir()
    (repo / "src/runtime.py").write_text(before)
    git(repo, "add", "src/runtime.py")
    git(repo, "commit", "-m", "complete runtime handle baseline")
    manager = GitWorktreeManager(repo, tmp_path / "roles")
    ref = manager.create(
        WorktreeSpec(
            task_id="task_runtime_handle",
            role=AgentRole.CODER,
            attempt=1,
            source_revision=git(repo, "rev-parse", "HEAD"),
        )
    )
    permissions = AgentPermissions(
        read_paths=("src/**",), write_paths=("src/**",), commands=(), network=NetworkAccess.NONE
    )
    after = before.replace("CAPTURE_VALUE = 1", "CAPTURE_VALUE = 2")
    source = ref.path / "src/runtime.py"
    source.write_text(after)
    index = Path(git(ref.path, "rev-parse", "--path-format=absolute", "--git-path", "index"))
    status = git(ref.path, "status", "--porcelain")
    index_bytes = index.read_bytes()
    if unsafe:
        with pytest.raises(WorktreeCaptureRejected, match="bounded regular text mutation bodies"):
            manager.capture_mutations(ref, permissions)
    else:
        capture = manager.capture_mutations(ref, permissions)
        assert len(capture.mutations) == 1
        mutation = capture.mutations[0]
        assert mutation.before is not None and mutation.before.text == before
        assert mutation.after is not None and mutation.after.text == after
        assert mutation.before.sha256 == hashlib.sha256(before.encode()).hexdigest()
        assert mutation.after.sha256 == hashlib.sha256(after.encode()).hexdigest()
        assert b"token" not in capture.patch
        wire = CapturedMutations.from_capture(capture).to_wire()
        assert CapturedMutations.model_validate(wire).to_capture() == capture
        manager.verify_mutations(capture, permissions)
    assert source.read_text() == after
    assert index.read_bytes() == index_bytes
    assert git(ref.path, "status", "--porcelain") == status
    assert git(ref.path, "rev-parse", "HEAD") == ref.head_revision
    assert git(repo, "status", "--porcelain") == ""
