"""Real-Git regular-text mutation capture is complete, read-only and fail-closed."""

import subprocess
from dataclasses import replace
from pathlib import Path

import pytest

from ai_software_engineer.domain import AgentPermissions, AgentRole
from ai_software_engineer.git import (
    GitWorktreeManager,
    PathPolicyViolation,
    WorktreeCaptureRejected,
    WorktreeSpec,
)
from ai_software_engineer.git.ports import WorktreeRef
from ai_software_engineer.orchestration.continuation_capture import CapturedMutations
from tests.git.test_capture import git
from tests.git.test_capture import workspace as workspace


@pytest.mark.parametrize(
    "code",
    [
        "def connect(settings):\n"
        "    return client(password=settings.password, host=settings.host)\n",
        'def fixture(foreign):\n    secret = foreign / "secret.json"\n    return secret\n',
    ],
)
def test_source_reference_is_captured_unchanged_through_wire_and_verify(
    workspace: tuple[GitWorktreeManager, WorktreeRef, AgentPermissions], code: str
) -> None:
    manager, ref, permissions = workspace
    path = ref.path / "src/new.py"
    path.write_text(code)
    index = Path(git(ref.path, "rev-parse", "--path-format=absolute", "--git-path", "index"))
    before_index = index.read_bytes()
    captured = manager.capture_mutations(ref, permissions)
    body = captured.mutations[0].after
    assert body is not None and body.text == code
    stored = CapturedMutations.from_capture(captured)
    assert CapturedMutations.model_validate(stored.to_wire()).to_capture() == captured
    manager.verify_mutations(captured, permissions)
    assert path.read_text() == code and index.read_bytes() == before_index


@pytest.mark.parametrize(
    "code",
    [
        'password = "clear-text-value"\n',
        "password=hunter2\n",
        "token=my.jwt.secret\n",
        "password=foo.bar\n",
        'password=settings.password; token="actual-value"\n',
        'secret = foreign / "sk-' + "x" * 24 + '.json"\n',
        'secret = foreign / "Bearer abcdefghijkl.json"\n',
        'payload = "password=settings.password;"\n',
        "# password=settings.password\n",
    ],
)
def test_source_reference_classifier_still_rejects_secret_values(
    workspace: tuple[GitWorktreeManager, WorktreeRef, AgentPermissions], code: str
) -> None:
    manager, ref, permissions = workspace
    source = ref.path / "src/new.py"
    source.write_text(code)
    with pytest.raises(WorktreeCaptureRejected):
        manager.capture_mutations(ref, permissions)
    assert source.read_text() == code


def test_staged_only_literal_still_blocks_capture_when_working_body_is_safe(
    workspace: tuple[GitWorktreeManager, WorktreeRef, AgentPermissions],
) -> None:
    manager, ref, permissions = workspace
    source = ref.path / "src/app.py"
    source.write_text('password="clear-text-value"\n')
    git(ref.path, "add", "src/app.py")
    source.write_text("password=settings.password\n")
    index = Path(git(ref.path, "rev-parse", "--path-format=absolute", "--git-path", "index"))
    before_index = index.read_bytes()
    with pytest.raises(WorktreeCaptureRejected):
        manager.capture_mutations(ref, permissions)
    assert index.read_bytes() == before_index
    assert source.read_text() == "password=settings.password\n"


def test_wire_mutation_parent_rechecks_source_language_from_its_actual_path(
    workspace: tuple[GitWorktreeManager, WorktreeRef, AgentPermissions],
) -> None:
    from pydantic import ValidationError

    manager, ref, permissions = workspace
    (ref.path / "src/new.py").write_text("token=settings.token\n")
    stored = CapturedMutations.from_capture(manager.capture_mutations(ref, permissions))
    payload = stored.to_wire()
    mutations = payload["mutations"]
    assert isinstance(mutations, list) and isinstance(mutations[0], dict)
    mutations[0]["path"] = "src/new.env"
    with pytest.raises(ValidationError, match="nonsensitive"):
        CapturedMutations.model_validate(payload)


@pytest.mark.parametrize("change", ["delete", "rename", "mode", "text_and_mode"])
def test_complete_patch_and_bodies_capture_common_changes_without_writes(
    workspace: tuple[GitWorktreeManager, WorktreeRef, AgentPermissions], change: str
) -> None:
    manager, ref, permissions = workspace
    source = ref.path / "src/app.py"
    original = source.read_text()
    index = Path(git(ref.path, "rev-parse", "--path-format=absolute", "--git-path", "index"))
    index_bytes = index.read_bytes()
    if change == "delete":
        source.unlink()
    elif change == "rename":
        source.rename(ref.path / "src/renamed.py")
    else:
        if change == "text_and_mode":
            source.write_text("VALUE = 2\n")
        source.chmod(0o755)
    before_status = git(ref.path, "status", "--porcelain")
    capture = manager.capture_mutations(ref, permissions)
    assert capture.changed_paths == (
        ("src/app.py", "src/renamed.py") if change == "rename" else ("src/app.py",)
    )
    assert capture.mutations[0].before is not None and capture.mutations[0].before.text == original
    if change in ("delete", "rename"):
        assert capture.mutations[0].after is None
        assert b"deleted file mode 100644" in capture.patch
    else:
        assert capture.mutations[0].after is not None and capture.mutations[0].after.mode == 0o755
        assert b"old mode 100644" in capture.patch and b"new mode 100755" in capture.patch
    if change == "rename":
        assert capture.mutations[1].before is None and capture.mutations[1].after is not None
        assert capture.mutations[1].after.text == original
        assert b"rename from" not in capture.patch
    persisted = CapturedMutations.from_capture(capture)
    assert persisted.to_capture() == capture
    assert CapturedMutations.model_validate(persisted.to_wire()) == persisted
    manager.verify_mutations(capture, permissions)
    assert index.read_bytes() == index_bytes
    assert git(ref.path, "status", "--porcelain") == before_status
    assert git(ref.path, "rev-parse", "HEAD") == ref.head_revision
    target = manager.create(
        WorktreeSpec(
            task_id="task_mutation_copy",
            role=AgentRole.CODER,
            attempt=1,
            source_revision=ref.head_revision,
        )
    )
    subprocess.run(
        ("git", "-c", "core.hooksPath=/dev/null", "apply", "--unidiff-zero", "-"),
        cwd=target.path,
        input=capture.patch,
        check=True,
        capture_output=True,
    )
    assert manager.capture_mutations(target, permissions).mutations == capture.mutations


@pytest.mark.parametrize("change", ["delete", "rename", "mode"])
def test_common_mutation_still_requires_exact_write_permission(
    workspace: tuple[GitWorktreeManager, WorktreeRef, AgentPermissions], change: str
) -> None:
    manager, ref, permissions = workspace
    source = ref.path / "src/app.py"
    if change == "delete":
        source.unlink()
    elif change == "rename":
        source.rename(ref.path / "src/renamed.py")
    else:
        source.chmod(0o755)
    for denied in (("src/app.py",), ("src/**",)):
        with pytest.raises(PathPolicyViolation):
            manager.capture_mutations(ref, permissions, denied_paths=denied)
    if change == "rename":
        with pytest.raises(PathPolicyViolation):
            manager.capture_mutations(ref, permissions, denied_paths=("src/renamed.py",))
    assert git(ref.path, "rev-parse", "HEAD") == ref.head_revision


@pytest.mark.parametrize("change", ["symlink", "fifo", "binary", "sensitive", "nonregular_mode"])
def test_mutation_refuses_unsupported_bodies_without_following_or_cleaning(
    workspace: tuple[GitWorktreeManager, WorktreeRef, AgentPermissions], change: str
) -> None:
    import os

    manager, ref, permissions = workspace
    source = ref.path / "src/app.py"
    if change == "symlink":
        source.unlink()
        source.symlink_to("missing.py")
    elif change == "fifo":
        source.unlink()
        os.mkfifo(source)
    elif change == "binary":
        source.write_bytes(b"abc\0def")
    elif change == "nonregular_mode":
        source.chmod(0o600)
        source.write_text("VALUE = 2\n")
    else:
        source.write_text('api_key = "sk-' + "x" * 24 + '"\n')
    with pytest.raises(WorktreeCaptureRejected) as caught:
        manager.capture_mutations(ref, permissions)
    assert "sk-" not in str(caught.value)
    assert git(ref.path, "rev-parse", "HEAD") == ref.head_revision
    assert source.exists() or source.is_symlink()


@pytest.mark.parametrize("drift", ["mode", "restore_deleted", "body", "index"])
def test_mutation_verify_rechecks_exact_mode_absence_body_and_index(
    workspace: tuple[GitWorktreeManager, WorktreeRef, AgentPermissions], drift: str
) -> None:
    manager, ref, permissions = workspace
    source = ref.path / "src/app.py"
    source.write_text("VALUE = 2\n")
    if drift == "restore_deleted":
        source.unlink()
    capture = manager.capture_mutations(ref, permissions)
    if drift == "mode":
        source.chmod(0o755)
    elif drift == "restore_deleted":
        source.write_text("VALUE = 1\n")
    elif drift == "body":
        source.write_text("VALUE = 3\n")
    else:
        git(ref.path, "add", "src/app.py")
    with pytest.raises(WorktreeCaptureRejected):
        manager.verify_mutations(capture, permissions)


def test_mutation_complete_patch_tampering_is_rejected(
    workspace: tuple[GitWorktreeManager, WorktreeRef, AgentPermissions],
) -> None:
    manager, ref, permissions = workspace
    (ref.path / "src/app.py").write_text("VALUE = 2\n")
    capture = manager.capture_mutations(ref, permissions)
    corrupted = replace(capture, patch=capture.patch.replace(b"+VALUE = 2", b"+VALUE = 99"))
    with pytest.raises(WorktreeCaptureRejected):
        manager.verify_mutations(corrupted, permissions)
