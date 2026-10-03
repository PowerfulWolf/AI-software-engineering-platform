"""The live read model decodes immutable route ledgers once per snapshot."""

from pathlib import Path

from ai_software_engineer.agents.fallback import FileModelRouteAttemptStore
from ai_software_engineer.team_view.reader import _ModelRouteAttemptCache


def test_model_route_attempt_cache_reuses_each_sidecar_ledger_within_snapshot(
    tmp_path: Path, monkeypatch
) -> None:
    root = tmp_path / "runs" / "model-routes"
    (root / "run_first").mkdir(parents=True)
    (root / "run_second").mkdir()
    calls: list[str] = []
    original = FileModelRouteAttemptStore.list_for_run

    def record(self: FileModelRouteAttemptStore, run_id: str):  # type: ignore[no-untyped-def]
        calls.append(run_id)
        return original(self, run_id)

    monkeypatch.setattr(FileModelRouteAttemptStore, "list_for_run", record)
    cache = _ModelRouteAttemptCache()

    assert cache.attempts(root) == ()
    assert cache.attempts(root) == ()

    assert calls == ["run_first", "run_second"]
