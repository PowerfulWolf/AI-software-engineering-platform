"""A Team read captures each complete Requirement prefix once, then releases it."""

from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

import pytest

from ai_software_engineer.config import ModelProviderKind, ProductionConfig, ProviderRouteConfig
from ai_software_engineer.multi_directory.models import JointCheckpoint, JointStage
from ai_software_engineer.multi_directory.retirement import RequirementRetirementStore
from ai_software_engineer.multi_directory.scope import DirectoryScope, DirectoryUnit
from ai_software_engineer.multi_directory.store import JointJournal
from ai_software_engineer.project_workspace import ProjectWorkspace
from ai_software_engineer.team_view.models import TeamReadError
from ai_software_engineer.team_view.reader import ProductionTeamReader, _Native, _read_native
from ai_software_engineer.team_workspace import TeamWorkspace


def _fixture(
    tmp_path: Path,
) -> tuple[ProductionTeamReader, ProjectWorkspace, JointJournal, JointCheckpoint]:
    config = ProductionConfig(
        platform_root=str(tmp_path / "platform"),
        model_routes=(
            ProviderRouteConfig(
                provider="codex", model="gpt-6.1-sol", kind=ModelProviderKind.CODEX_CLI
            ),
        ),
    )
    team = TeamWorkspace.initialize(
        config.platform_root, team_id=config.team_id, name=config.team_name
    )
    project = team.project_registry().register(project_id="project_test", name="Test Project")
    repository = tmp_path / "repository"
    repository.mkdir()
    first = JointCheckpoint.seal(
        {
            "delivery_id": "delivery_multi_retired_snapshot",
            "team_id": team.manifest.team_id,
            "team_manifest_sha256": team.manifest.manifest_sha256,
            "project_id": project.manifest.project_id,
            "project_manifest_sha256": project.manifest.manifest_sha256,
            "sequence": 1,
            "stage": JointStage.PREPARING,
            "scope": DirectoryScope(
                units=(
                    DirectoryUnit(
                        id="unit_" + "a" * 16,
                        root=str(repository),
                        selected_paths=(".",),
                        base_revision="a" * 40,
                    ),
                )
            ),
            "title": "Retained historical draft",
            "submitted_at": datetime.now(UTC),
            "next_action": "Prepare the repository",
        }
    )
    journal = JointJournal(project.requirements_root)
    journal.append(first, expected=None)
    last = JointCheckpoint.seal(
        {
            **first.to_wire(),
            "sequence": 2,
            "previous_checkpoint_sha256": first.checkpoint_sha256,
            "next_action": "Retained complete history",
        }
    )
    journal.append(last, expected=first.checkpoint_sha256)
    current = JointCheckpoint.seal(
        {
            **first.to_wire(),
            "delivery_id": "delivery_multi_current_snapshot",
            "title": "Current draft",
        }
    )
    journal.append(current, expected=None)
    RequirementRetirementStore(
        project.requirements_root,
        team_id=team.manifest.team_id,
        team_manifest_sha256=team.manifest.manifest_sha256,
        project_id=project.manifest.project_id,
        project_manifest_sha256=project.manifest.manifest_sha256,
    ).retire(
        last,
        reason="replaced",
        replacement_delivery_id=current.delivery_id,
        retired_at=datetime.now(UTC),
    )
    return ProductionTeamReader(config, {}), project, journal, current


def test_snapshot_reads_retired_and_replacement_history_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    reader, project, journal, current = _fixture(tmp_path)
    calls: Counter[str] = Counter()
    original = JointJournal.history

    def history(store: JointJournal, delivery_id: str) -> tuple[JointCheckpoint, ...]:
        calls[delivery_id] += 1
        return original(store, delivery_id)

    monkeypatch.setattr(JointJournal, "history", history)
    snapshot = reader.snapshot(project.manifest.project_id)

    assert calls == {
        "delivery_multi_retired_snapshot": 1,
        "delivery_multi_current_snapshot": 1,
    }
    assert [request.id for request in snapshot.requests] == [current.delivery_id]
    assert snapshot.projects[0].requirement_count == 1
    assert len(original(journal, "delivery_multi_retired_snapshot")) == 2


def test_next_snapshot_observes_appended_history(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    reader, project, journal, current = _fixture(tmp_path)
    previous_snapshot = reader.snapshot(project.manifest.project_id)
    assert previous_snapshot.requests[0].next_action == current.next_action
    next_checkpoint = JointCheckpoint.seal(
        {
            **current.to_wire(),
            "sequence": 2,
            "previous_checkpoint_sha256": current.checkpoint_sha256,
            "next_action": "Newly published work is visible",
        }
    )
    journal.append(next_checkpoint, expected=current.checkpoint_sha256)
    calls: Counter[str] = Counter()
    original = JointJournal.history

    def history(store: JointJournal, delivery_id: str) -> tuple[JointCheckpoint, ...]:
        calls[delivery_id] += 1
        return original(store, delivery_id)

    monkeypatch.setattr(JointJournal, "history", history)
    snapshot = reader.snapshot(project.manifest.project_id)
    assert snapshot.requests[0].next_action == next_checkpoint.next_action
    assert calls == {
        "delivery_multi_retired_snapshot": 1,
        "delivery_multi_current_snapshot": 1,
    }


def test_selected_project_count_uses_the_captured_directory_prefix(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    reader, project, journal, current = _fixture(tmp_path)
    published = JointCheckpoint.seal(
        {
            **current.to_wire(),
            "delivery_id": "delivery_multi_published_during_snapshot",
            "title": "Published after the captured Requirement prefix",
        }
    )

    def native_with_concurrent_publish(current_project: ProjectWorkspace) -> tuple[_Native, ...]:
        journal.append(published, expected=None)
        return _read_native(current_project)

    with monkeypatch.context() as patch:
        patch.setattr(
            "ai_software_engineer.team_view.reader._read_native", native_with_concurrent_publish
        )
        snapshot = reader.snapshot(project.manifest.project_id)
    assert [request.id for request in snapshot.requests] == [current.delivery_id]
    assert snapshot.projects[0].requirement_count == 1
    next_snapshot = reader.snapshot(project.manifest.project_id)
    assert next_snapshot.projects[0].requirement_count == 2
    assert {request.id for request in next_snapshot.requests} == {
        current.delivery_id,
        published.delivery_id,
    }


def test_other_project_counts_reuse_shared_replacement_history(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    reader, project, _journal, current = _fixture(tmp_path)
    other = project.team.project_registry().register(
        project_id="project_other", name="Other Project"
    )
    other_journal = JointJournal(other.requirements_root)
    replacement = JointCheckpoint.seal(
        {
            **current.to_wire(),
            "delivery_id": "delivery_multi_other_replacement",
            "project_id": other.manifest.project_id,
            "project_manifest_sha256": other.manifest.manifest_sha256,
        }
    )
    other_journal.append(replacement, expected=None)
    retirements = RequirementRetirementStore(
        other.requirements_root,
        team_id=other.team.manifest.team_id,
        team_manifest_sha256=other.team.manifest.manifest_sha256,
        project_id=other.manifest.project_id,
        project_manifest_sha256=other.manifest.manifest_sha256,
    )
    for index in range(2):
        retired = JointCheckpoint.seal(
            {**replacement.to_wire(), "delivery_id": f"delivery_multi_other_retired_{index}"}
        )
        other_journal.append(retired, expected=None)
        retirements.retire(
            retired,
            reason="replaced",
            replacement_delivery_id=replacement.delivery_id,
            retired_at=datetime.now(UTC),
        )
    calls: Counter[str] = Counter()
    original = JointJournal.history

    def history(store: JointJournal, delivery_id: str) -> tuple[JointCheckpoint, ...]:
        calls[delivery_id] += 1
        return original(store, delivery_id)

    monkeypatch.setattr(JointJournal, "history", history)
    snapshot = reader.snapshot(project.manifest.project_id)
    assert calls == {
        "delivery_multi_retired_snapshot": 1,
        "delivery_multi_current_snapshot": 1,
        "delivery_multi_other_replacement": 1,
        "delivery_multi_other_retired_0": 1,
        "delivery_multi_other_retired_1": 1,
    }
    assert [request.id for request in snapshot.requests] == [current.delivery_id]
    assert {item.id: item.requirement_count for item in snapshot.projects} == {
        project.manifest.project_id: 1,
        other.manifest.project_id: 1,
    }


@pytest.mark.parametrize(
    "change", ["body", "missing-ancestor", "symlink", "retirement", "missing-replacement"]
)
def test_next_snapshot_revalidates_retired_history_and_visibility(
    tmp_path: Path, change: str
) -> None:
    reader, project, journal, current = _fixture(tmp_path)
    assert reader.snapshot(project.manifest.project_id).projects[0].requirement_count == 1
    ancestor = journal.directory("delivery_multi_retired_snapshot") / "000001.json"
    if change == "body":
        ancestor.write_bytes(ancestor.read_bytes().replace(b"Retained", b"Tampered"))
    elif change == "missing-ancestor":
        ancestor.unlink()
    elif change == "symlink":
        external = tmp_path / "external.json"
        external.write_bytes(ancestor.read_bytes())
        ancestor.unlink()
        ancestor.symlink_to(external)
    elif change == "retirement":
        path = project.requirements_root / "retirement.json"
        path.write_bytes(path.read_bytes().replace(b"replaced", b"deleted!"))
    else:
        (journal.directory(current.delivery_id) / "000001.json").unlink()

    with pytest.raises(TeamReadError):
        reader.snapshot(project.manifest.project_id)
