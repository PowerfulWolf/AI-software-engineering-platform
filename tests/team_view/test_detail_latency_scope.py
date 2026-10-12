"""Exact detail reads omit unused metadata and hydrate only body fields."""

from pathlib import Path

import pytest

from ai_software_engineer.team_view import reader as read_module
from ai_software_engineer.team_view.read_models import TeamDetailQuery
from ai_software_engineer.team_view.reader import ProductionTeamReader
from ai_software_engineer.team_workspace import discover_team_workspaces
from tests.team_view.test_baseline_snapshot import _fixture, _read_snapshot_fixture
from tests.team_view.test_live import _historical_child_fixture


def test_compact_to_complete_body_does_not_rebuild_current_engineering_facts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = _fixture(tmp_path)
    reads, native, base, dispatch = _read_snapshot_fixture(fixture, monkeypatch)
    original = read_module._read_task_details
    calls = 0

    def counted(*args: object, **kwargs: object) -> object:
        nonlocal calls
        calls += 1
        return original(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(read_module, "_read_task_details", counted)
    compact = reads.read(native, base, dispatch_override=dispatch, include_details=False)
    complete = reads.read(native, base, dispatch_override=dispatch, include_details=True)
    assert calls == 1
    assert complete.timeline == compact.timeline
    assert complete.role_queue == compact.role_queue
    assert complete.execution == compact.execution
    assert complete.task_intent_sha256 == compact.task_intent_sha256
    expected, _, _, _ = _read_snapshot_fixture(fixture, monkeypatch)
    assert expected.read(native, base, dispatch_override=dispatch) == complete


def test_body_hydration_rereads_original_artifacts_and_does_not_save_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = _fixture(tmp_path)
    reads, native, base, dispatch = _read_snapshot_fixture(fixture, monkeypatch)
    original = read_module._read_accepted_artifact_history
    calls = 0

    def changed(*args: object, **kwargs: object) -> object:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise ValueError("original accepted artifact changed")
        return original(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(read_module, "_read_accepted_artifact_history", changed)
    reads.read(native, base, dispatch_override=dispatch, include_details=False)
    with pytest.raises(ValueError, match="original accepted artifact changed"):
        reads.read(native, base, dispatch_override=dispatch, include_details=True)
    reads.read(native, base, dispatch_override=dispatch, include_details=True)
    assert calls == 3


def test_detail_and_fresh_source_fence_do_not_read_unrelated_project_retirement(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config, _, _, _ = _historical_child_fixture(tmp_path)
    reader = ProductionTeamReader(config, {})
    team = discover_team_workspaces(config.platform_root)[0]
    other = team.project_registry().register(project_id="project_other", name="Other")
    query = TeamDetailQuery.from_source(reader.summary("project_test").requests[0].detail_source)
    original = read_module._retired_requirement_ids
    selected_calls = 0

    def retired(project: object, journal: object) -> frozenset[str]:
        nonlocal selected_calls
        assert project != other, "a selected body does not need unrelated Project counts"
        selected_calls += 1
        return original(project, journal)  # type: ignore[arg-type]

    monkeypatch.setattr(read_module, "_retired_requirement_ids", retired)
    detail = reader.detail(query)
    assert detail.scope == query.source()
    assert selected_calls == 2, "the selected source must still be freshly observed after body"
