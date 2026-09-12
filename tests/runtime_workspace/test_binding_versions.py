"""Versioned binding records preserve legacy bytes and remain revision-bound."""

from datetime import timedelta
from pathlib import Path

import pytest

from ai_software_engineer.repository_profile import RepositoryProfile
from ai_software_engineer.runtime_workspace import (
    RuntimeWorkspaceBinder,
    RuntimeWorkspaceConflict,
    RuntimeWorkspaceCorruption,
    load_repository_profile,
)
from tests.runtime_workspace.test_binding import NOW, bind


@pytest.mark.parametrize("damage", ["corrupt", "symlink"])
def test_versioned_binding_preserves_legacy_and_rejects_damage(tmp_path: Path, damage: str) -> None:
    org, workspace, old_profile, project, old_binding = bind(tmp_path)
    before = {p: p.read_bytes() for p in workspace.root.rglob("*.json")}
    binder = RuntimeWorkspaceBinder(versioned=True)
    assert (
        binder.bind(org, workspace, old_profile, bound_at=NOW + timedelta(hours=1)) == old_binding
    )
    (project / "README.md").write_text("second baseline\n")
    profile = RepositoryProfile.discover(
        project, repository_id=workspace.repository_id, observed_at=NOW
    )
    current = binder.bind(org, workspace, profile, bound_at=NOW + timedelta(hours=2))
    assert current.repository_id == old_binding.repository_id
    assert current.binding_sha256 != old_binding.binding_sha256
    assert all(p.read_bytes() == content for p, content in before.items())
    assert load_repository_profile(workspace.root, old_profile.profile_sha256) == old_profile
    assert binder.bind(org, workspace, profile, bound_at=NOW + timedelta(hours=3)) == current
    with pytest.raises(RuntimeWorkspaceConflict, match="target repository facts changed"):
        old_binding.validate_environment()
    record = workspace.directory("profile") / f"repository-profile-{profile.profile_sha256}.json"
    if damage == "corrupt":
        record.write_text("{}")
    else:
        external = tmp_path / "external.json"
        external.write_bytes(record.read_bytes())
        record.unlink()
        record.symlink_to(external)
    with pytest.raises(RuntimeWorkspaceCorruption):
        current.validate_environment()
    assert all(p.read_bytes() == content for p, content in before.items())
