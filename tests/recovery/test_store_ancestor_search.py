"""No-follow directory chains read only their target; ancestors are search-only."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from ai_software_engineer.orchestration import continuation_store
from ai_software_engineer.recovery import store


@pytest.mark.parametrize("module", (store, continuation_store))
def test_only_the_target_directory_is_opened_for_reading(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, module: object
) -> None:
    target = (tmp_path / "a" / "b").resolve()
    target.mkdir(parents=True)
    real_open = os.open
    seen: list[tuple[str, int]] = []

    def recording_open(path: str, flags: int, *args: object, **kwargs: object) -> int:
        seen.append((path, flags))
        return real_open(path, flags, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(os, "open", recording_open)
    descriptor = module._open_directory(target)  # type: ignore[attr-defined]
    try:
        assert os.fstat(descriptor).st_ino == target.stat().st_ino
        assert sorted(os.listdir(descriptor)) == []
    finally:
        os.close(descriptor)
    assert [name for name, _ in seen] == ["/", *target.parts[1:]]
    search = module._SEARCH  # type: ignore[attr-defined]
    assert all(flags & search == search for _, flags in seen[:-1])
    assert all(flags & os.O_NOFOLLOW for _, flags in seen[1:])
    if search != os.O_RDONLY:
        assert seen[-1][1] & search != search


@pytest.mark.parametrize(
    ("module", "error"),
    (
        (store, store.RecoveryRejected),
        (continuation_store, continuation_store.ContinuationRejected),
    ),
)
def test_symlinked_ancestor_is_still_rejected(tmp_path: Path, module: object, error: type) -> None:
    real = (tmp_path / "real").resolve()
    (real / "leaf").mkdir(parents=True)
    (tmp_path / "link").symlink_to(real)
    with pytest.raises(error):
        module._open_directory(tmp_path.resolve() / "link" / "leaf")  # type: ignore[attr-defined]
