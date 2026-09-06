"""Company ownership and selected knowledge must not pollute or mix code projects."""

import json
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import Mock

import pytest

from ai_software_engineer.company_workspace import CompanyWorkspace
from ai_software_engineer.multi_directory.models import JointCheckpoint, JointStage
from ai_software_engineer.multi_directory.scope import DirectoryScope, DirectoryUnit
from ai_software_engineer.multi_directory.service import JointBackend, JointDeliveryService


def company(root: Path, suffix: str = "alpha") -> CompanyWorkspace:
    return CompanyWorkspace.initialize(root, company_id=f"company_{suffix}", name=suffix)


def test_one_company_collects_projects_without_copying_code(tmp_path: Path) -> None:
    workspace = company(tmp_path / "platform")
    for name in ("backend", "frontend"):
        project = tmp_path / name
        project.mkdir()
        (project / "source.txt").write_text("code", encoding="utf-8")
        module = workspace.project_registry().register(project)
        assert module.root.parent == workspace.root / "projects"
        assert list(project.iterdir()) == [project / "source.txt"]
        assert not (module.root / "source.txt").exists()
    assert workspace.requests_root == workspace.root / "requests"
    assert company(tmp_path / "platform").manifest == workspace.manifest
    assert not (workspace.root / "agents").exists()


def test_company_namespace_isolates_same_source_path(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    alpha = company(tmp_path / "platform", "alpha")
    beta = company(tmp_path / "platform", "beta")
    first = alpha.project_registry().register(repo)
    second = beta.project_registry().register(repo)
    assert first.project_id != second.project_id
    assert first.root != second.root
    with pytest.raises(ValueError, match="company"):
        alpha.project_registry().register(repo, project_id=second.project_id)


def test_manifest_changes_and_symlinks_are_rejected(tmp_path: Path) -> None:
    workspace = company(tmp_path / "platform")
    manifest = workspace.root / "company.json"
    data = json.loads(manifest.read_text())
    data["name"] = "tampered"
    manifest.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="digest"):
        company(tmp_path / "platform")
    other = company(tmp_path / "other")
    (other.root / "knowledge").rmdir()
    (other.root / "knowledge").symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(ValueError, match="symlink"):
        company(tmp_path / "other")


def test_selected_knowledge_is_readonly_redacted_and_company_scoped(tmp_path: Path) -> None:
    alpha = company(tmp_path / "platform", "alpha")
    beta = company(tmp_path / "platform", "beta")
    (alpha.root / "knowledge" / "rules.md").write_text("Review required. password=private-value")
    (alpha.root / "knowledge" / "unrelated.md").write_text("DO NOT LOAD")
    (beta.root / "knowledge" / "rules.md").write_text("OTHER COMPANY")
    sources = alpha.knowledge_sources(("rules.md",))
    assert len(sources) == 1
    assert "private-value" not in str(sources)
    assert "REDACTED" in str(sources)
    assert "DO NOT LOAD" not in str(sources)
    assert "OTHER COMPANY" not in str(sources)
    assert sources[0].uri.startswith("company://company_alpha/")
    assert alpha.knowledge_sources(()) == ()


@pytest.mark.parametrize(
    "path", ["../company.json", "/etc/passwd", ".env", "a//b", "./rules.md", "secret.pem"]
)
def test_knowledge_escape_and_secret_files_rejected(tmp_path: Path, path: str) -> None:
    with pytest.raises(ValueError):
        company(tmp_path / "platform").knowledge_sources((path,))


def test_company_storage_cannot_be_inside_registered_code(tmp_path: Path) -> None:
    workspace = company(tmp_path / "platform")
    with pytest.raises(ValueError, match="overlap"):
        workspace.project_registry().register(tmp_path)
    with pytest.raises(ValueError, match="overlap"):
        workspace.project_registry().register(workspace.root / "knowledge")


def test_requirement_journal_binds_company_not_only_directory(tmp_path: Path) -> None:
    alpha = company(tmp_path / "platform", "alpha")
    beta = company(tmp_path / "platform", "beta")
    backend = Mock(spec=JointBackend)
    first = JointDeliveryService(backend=backend, company=alpha)
    second = JointDeliveryService(backend=backend, company=beta)
    scope = DirectoryScope(
        units=(
            DirectoryUnit(
                id="unit_" + "a" * 16,
                root=str(tmp_path / "code"),
                selected_paths=(".",),
                base_revision=None,
            ),
        )
    )
    checkpoint = JointCheckpoint.seal(
        {
            "delivery_id": "delivery_multi_example",
            "company_id": alpha.manifest.company_id,
            "company_manifest_sha256": alpha.manifest.manifest_sha256,
            "sequence": 1,
            "stage": JointStage.PREPARING,
            "scope": scope,
            "title": "Joint change",
            "submitted_at": datetime.now(UTC),
            "next_action": "Prepare code scope",
        }
    )
    first.journal.append(checkpoint, expected=None)
    assert first.journal.root == alpha.requests_root
    assert first.status(checkpoint.delivery_id).checkpoint == checkpoint
    with pytest.raises(ValueError, match="not found"):
        second.status(checkpoint.delivery_id)
    # Even a copied valid journal is not authorized in another Company.
    second.journal.append(checkpoint, expected=None)
    with pytest.raises(ValueError, match="another company"):
        second.status(checkpoint.delivery_id)
    assert backend.reconcile.call_count == 1


def test_knowledge_symlink_encoding_budget_and_missing_record(tmp_path: Path) -> None:
    workspace = company(tmp_path / "platform")
    knowledge = workspace.root / "knowledge"
    (knowledge / "outside.md").symlink_to(tmp_path / "other.md")
    with pytest.raises(ValueError, match="symlink"):
        workspace.knowledge_sources(("outside.md",))
    (knowledge / "binary.md").write_bytes(b"\xff")
    with pytest.raises(UnicodeDecodeError):
        workspace.knowledge_sources(("binary.md",))
    (knowledge / "large.md").write_bytes(b"x" * 256_001)
    with pytest.raises(ValueError, match="budget"):
        workspace.knowledge_sources(("large.md",))
    (workspace.root / "company.json").unlink()
    with pytest.raises(ValueError, match="missing"):
        workspace.validate_current()
    assert not (workspace.root / "company.json").exists()
