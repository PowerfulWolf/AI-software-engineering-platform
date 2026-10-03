"""Historical profiles are extended only from exact candidate Git tree facts."""

import subprocess
from pathlib import Path
from unittest.mock import Mock

import pytest

from ai_software_engineer.recovery.models import RecoveryRejected
from ai_software_engineer.recovery.verification_entry import _verification_task_commands
from ai_software_engineer.recovery.verification_native import NativeCandidateSource
from ai_software_engineer.repository_profile import BuildSystem, BuildSystemFact, RepositoryProfile
from ai_software_engineer.swift_verification import SWIFT_VERIFICATION_COMMANDS


def _git(root: Path, *args: str) -> str:
    return subprocess.run(
        ("git", "-c", "core.hooksPath=/dev/null", *args),
        cwd=root,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()


@pytest.mark.parametrize("marker", ["file", "symlink", "directory", "absent"])
def test_swift_commands_follow_candidate_tree_not_current_checkout(
    tmp_path: Path, marker: str
) -> None:
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.name", "Test")
    _git(tmp_path, "config", "user.email", "test@example.invalid")
    (tmp_path / "README.md").write_text("fixture\n")
    _git(tmp_path, "add", "README.md")
    _git(tmp_path, "commit", "-qm", "baseline")
    historical = RepositoryProfile.discover(tmp_path)
    # The platform repository profile can contain Swift fixtures even when the
    # candidate itself is Python. The candidate marker must remain authoritative.
    historical = historical.model_copy(
        update={
            "build_systems": (
                BuildSystemFact(
                    system=BuildSystem.SWIFT,
                    markers=("tests/fixtures/swift-sandbox/Package.swift",),
                ),
            )
        }
    )
    before = historical.to_wire()
    package = tmp_path / "Package.swift"
    if marker == "file":
        package.write_text("// swift-tools-version: 6.0\n")
    elif marker == "symlink":
        package.symlink_to("README.md")
    elif marker == "directory":
        package.mkdir()
        (package / "not-a-manifest.txt").write_text("fixture\n")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "--allow-empty", "-qm", "candidate")
    candidate = _git(tmp_path, "rev-parse", "HEAD")
    # Opposite working-tree state must not affect the candidate observation.
    if marker == "file":
        package.unlink()
    elif marker == "absent":
        package.write_text("// unrelated current checkout\n")
    source = Mock(
        spec=NativeCandidateSource,
        scope=Mock(repository_root=str(tmp_path)),
        inputs=Mock(candidate_revision=candidate),
    )

    commands = _verification_task_commands(source, historical)

    assert (set(SWIFT_VERIFICATION_COMMANDS) <= set(commands)) is (marker == "file")
    assert historical.to_wire() == before
    assert not {"swift", "xcodebuild", "bash", "./Scripts/build-app.sh"} & set(commands)
    source.inputs.candidate_revision = "f" * 40
    with pytest.raises(RecoveryRejected, match="cannot inspect"):
        _verification_task_commands(source, historical)
