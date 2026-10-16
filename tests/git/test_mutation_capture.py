"""Real-Git regular-text mutation capture is complete, read-only and fail-closed."""

import hashlib
import subprocess
from dataclasses import replace
from pathlib import Path

import pytest

from ai_software_engineer.domain import AgentPermissions, AgentRole, NetworkAccess
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


@pytest.mark.parametrize("literal", [False, True], ids=["runtime-reference", "literal-rejected"])
def test_capture_preserves_complete_baseline_with_runtime_url_password(
    tmp_path: Path, literal: bool
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "--initial-branch=main")
    git(repo, "config", "user.name", "Fixture")
    git(repo, "config", "user.email", "fixture@example.invalid")
    (repo / "src").mkdir()
    before = (
        "from urllib.parse import unquote\n\n"
        "def parse(parsed):\n"
        "    return Settings(password=unquote(parsed.password))\n\n"
        "VALUE = 1\n"
    )
    if literal:
        before = before.replace("unquote(parsed.password)", 'unquote("clear-text")')
    (repo / "src/app.py").write_text(before, encoding="utf-8")
    git(repo, "add", "src/app.py")
    git(repo, "commit", "-m", "runtime URL credential reference")
    manager = GitWorktreeManager(repo, tmp_path / "roles")
    ref = manager.create(
        WorktreeSpec(
            task_id="task_capture_runtime_url",
            role=AgentRole.CODER,
            attempt=1,
            source_revision=git(repo, "rev-parse", "HEAD"),
        )
    )
    permissions = AgentPermissions(
        read_paths=("src/**",),
        write_paths=("src/**",),
        commands=(),
        network=NetworkAccess.NONE,
    )
    after = before.replace("VALUE = 1", "VALUE = 2")
    source = ref.path / "src/app.py"
    source.write_text(after, encoding="utf-8")
    index = Path(git(ref.path, "rev-parse", "--path-format=absolute", "--git-path", "index"))
    before_status = git(ref.path, "status", "--porcelain")
    index_bytes = index.read_bytes()

    if literal:
        with pytest.raises(WorktreeCaptureRejected, match="bounded regular text mutation bodies"):
            manager.capture_mutations(ref, permissions)
        assert source.read_text(encoding="utf-8") == after
        assert index.read_bytes() == index_bytes
        assert git(ref.path, "rev-parse", "HEAD") == ref.head_revision
        return

    capture = manager.capture_mutations(ref, permissions)

    assert len(capture.mutations) == 1
    mutation = capture.mutations[0]
    assert mutation.before is not None and mutation.before.text == before
    assert mutation.after is not None and mutation.after.text == after
    assert mutation.before.sha256 == hashlib.sha256(before.encode()).hexdigest()
    assert mutation.after.sha256 == hashlib.sha256(after.encode()).hexdigest()
    assert b"password" not in capture.patch
    stored = CapturedMutations.from_capture(capture)
    assert CapturedMutations.model_validate(stored.to_wire()).to_capture() == capture
    manager.verify_mutations(capture, permissions)
    assert source.read_text(encoding="utf-8") == after
    assert index.read_bytes() == index_bytes
    assert git(ref.path, "status", "--porcelain") == before_status
    assert git(ref.path, "rev-parse", "HEAD") == ref.head_revision


@pytest.mark.parametrize(
    "code",
    [
        "def connect(settings):\n"
        "    return client(password=settings.password, host=settings.host)\n",
        'def fixture(foreign):\n    secret = foreign / "secret.json"\n    return secret\n',
        "from dataclasses import dataclass, field\n"
        "@dataclass\nclass Session:\n    token: str = field(repr=False)\n",
        "import secrets\ndef issue():\n    token = secrets.token_urlsafe(32)\n    return token\n",
        "def read(row):\n    token: object = row['token_hash']\n    return token\n",
        "import secrets\ndef test_negative():\n"
        "    credential = secrets.token_urlsafe(32)\n"
        '    return f"https://example.invalid/check?token={credential}"\n',
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


def test_legacy_capture_includes_policy_authorized_ignored_source_without_changing_default(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "--initial-branch=main")
    git(repo, "config", "user.name", "Fixture")
    git(repo, "config", "user.email", "fixture@example.invalid")
    (repo / "src").mkdir()
    (repo / "src/app.py").write_text("VALUE = 1\n", encoding="utf-8")
    (repo / ".gitignore").write_text("artifacts/\n", encoding="utf-8")
    git(repo, "add", "src/app.py", ".gitignore")
    git(repo, "commit", "-m", "ignore generated artifacts")
    manager = GitWorktreeManager(repo, tmp_path / "roles")
    ref = manager.create(
        WorktreeSpec(
            task_id="task_capture_ignored",
            role=AgentRole.CODER,
            attempt=1,
            source_revision=git(repo, "rev-parse", "HEAD"),
        )
    )
    permissions = AgentPermissions(
        read_paths=("src/**",),
        write_paths=("src/**",),
        commands=(),
        network=NetworkAccess.NONE,
    )
    ignored = ref.path / "src" / "artifacts" / "accepted.py"
    ignored.parent.mkdir()
    ignored.write_text("VALUE = 2\n", encoding="utf-8")

    ordinary = manager.capture_mutations(ref, permissions)
    assert "src/artifacts/accepted.py" not in ordinary.changed_paths

    legacy = manager.capture_mutations(ref, permissions, include_ignored=True)
    assert "src/artifacts/accepted.py" in legacy.changed_paths
    manager.verify_mutations(legacy, permissions)
    assert ignored.read_text(encoding="utf-8") == "VALUE = 2\n"


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
        'token: str = "clear-text-value"\n',
        'from dataclasses import field\ntoken: str = field(default="clear-text-value")\n',
        "import secrets\nsecrets = factory\ntoken = secrets.token_urlsafe(32)\n",
        'import secrets\ntoken = secrets.token_urlsafe("clear-text-value")\n',
        "import secrets\ndef mutate(mod):\n"
        "    mod.token_urlsafe = lambda n: 'clear-text-value'\n"
        "mutate(secrets)\ntoken = secrets.token_urlsafe(32)\n",
        "import secrets\nexecute = exec\nexecute(code)\ntoken = secrets.token_urlsafe(32)\n",
        "import secrets\ndef test_negative():\n"
        '    credential = "fixed-value"\n    return f"token={credential}"\n',
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


@pytest.mark.parametrize(
    ("unsafe", "safe"),
    [
        ('password="clear-text-value"\n', "password=settings.password\n"),
        ('token: str = "clear-text-value"\n', "token: object = row['token_hash']\n"),
    ],
)
def test_staged_only_literal_still_blocks_capture_when_working_body_is_safe(
    workspace: tuple[GitWorktreeManager, WorktreeRef, AgentPermissions],
    unsafe: str,
    safe: str,
) -> None:
    manager, ref, permissions = workspace
    source = ref.path / "src/app.py"
    source.write_text(unsafe)
    git(ref.path, "add", "src/app.py")
    source.write_text(safe)
    index = Path(git(ref.path, "rev-parse", "--path-format=absolute", "--git-path", "index"))
    before_index = index.read_bytes()
    with pytest.raises(WorktreeCaptureRejected):
        manager.capture_mutations(ref, permissions)
    assert index.read_bytes() == before_index
    assert source.read_text() == safe


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


def test_automatic_cleanup_preserves_ignored_only_source(
    workspace: tuple[GitWorktreeManager, WorktreeRef, AgentPermissions],
) -> None:
    from ai_software_engineer.git import DirtyWorktree

    manager, ref, _ = workspace
    common = Path(git(ref.path, "rev-parse", "--path-format=absolute", "--git-common-dir"))
    (common / "info" / "exclude").write_text("artifacts/\n")
    source = ref.path / "src/artifacts/accepted.py"
    source.parent.mkdir()
    source.write_text("VALUE = 42\n")
    assert not manager.inspect(ref).dirty
    with pytest.raises(DirtyWorktree):
        manager.remove(ref)
    assert source.read_text() == "VALUE = 42\n"
    assert git(ref.path, "rev-parse", "HEAD") == ref.head_revision


def test_automatic_cleanup_allows_explicit_execution_caches(
    workspace: tuple[GitWorktreeManager, WorktreeRef, AgentPermissions],
) -> None:
    manager, ref, _ = workspace
    common = Path(git(ref.path, "rev-parse", "--path-format=absolute", "--git-common-dir"))
    (common / "info" / "exclude").write_text("__pycache__/\n.pytest_cache/\n.ruff_cache/\n")
    for name in ("__pycache__/app.pyc", ".pytest_cache/state", ".ruff_cache/state"):
        path = ref.path / name
        path.parent.mkdir()
        path.write_bytes(b"cache\0")
    manager.remove(ref)
    assert not ref.path.exists()
