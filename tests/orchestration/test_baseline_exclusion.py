"""A trusted baseline retirement cannot revive normal supersedes ancestors."""

from datetime import timedelta

import pytest

from ai_software_engineer.artifacts import seal_artifact
from ai_software_engineer.artifacts.ordering import ArtifactOrderingError, latest_accepted_artifact
from ai_software_engineer.domain.artifact import Artifact, CoderProgressArtifact
from tests.domain.factories import NOW, make_coder_progress_artifact, make_plan_artifact


def _progress(identity: str, *, supersedes: str | None = None) -> CoderProgressArtifact:
    sealed = seal_artifact(
        make_coder_progress_artifact().model_copy(
            update={"artifact_id": identity, "supersedes": supersedes}
        ),
        validated_at=NOW,
    )
    assert isinstance(sealed, CoderProgressArtifact)
    return sealed


def test_retiring_latest_progress_keeps_all_explicit_old_checkpoints_retired() -> None:
    old = _progress("art_progress_old")
    middle = _progress("art_progress_middle", supersedes=old.artifact_id)
    latest = _progress("art_progress_latest", supersedes=middle.artifact_id)
    history: tuple[Artifact, ...] = (middle, latest, old)
    excluded = frozenset((latest.artifact_id,))
    assert (
        latest_accepted_artifact(history, CoderProgressArtifact, excluded_artifact_ids=excluded)
        is None
    )
    new = _progress("art_progress_new", supersedes=latest.artifact_id)
    assert (
        latest_accepted_artifact(
            (*history, new), CoderProgressArtifact, excluded_artifact_ids=excluded
        )
        == new
    )


def test_exclusion_retains_full_graph_for_transitive_order() -> None:
    first = _progress("art_progress_first")
    retired = _progress("art_progress_retired")
    bridge = seal_artifact(
        make_plan_artifact().model_copy(
            update={
                "artifact_id": "art_plan_bridge",
                "parent_artifact_ids": (retired.artifact_id, first.artifact_id),
            }
        ),
        validated_at=NOW,
    )
    last = seal_artifact(
        _progress("art_progress_last").model_copy(
            update={"parent_artifact_ids": (bridge.artifact_id,)}
        ),
        validated_at=NOW,
    )
    assert (
        latest_accepted_artifact(
            (last, retired, first, bridge),
            CoderProgressArtifact,
            excluded_artifact_ids=frozenset((retired.artifact_id,)),
        )
        == last
    )


def test_unrelated_old_progress_is_not_ignored_by_revision_or_time() -> None:
    retired = _progress("art_progress_retired")
    unrelated = seal_artifact(
        _progress("art_progress_unrelated").model_copy(update={"source_revision": "f" * 40}),
        validated_at=NOW - timedelta(seconds=1),
    )
    assert (
        latest_accepted_artifact(
            (retired, unrelated),
            CoderProgressArtifact,
            excluded_artifact_ids=frozenset((retired.artifact_id,)),
        )
        == unrelated
    )


@pytest.mark.parametrize("fault", ["unsealed", "duplicate", "cycle", "cross_kind"])
def test_exclusion_does_not_hide_invalid_accepted_history(fault: str) -> None:
    retired = _progress("art_progress_retired")
    if fault == "unsealed":
        original = make_coder_progress_artifact()
        unsealed = original.model_copy(
            update={
                "integrity": original.integrity.model_copy(
                    update={"validated": False, "validated_at": None}
                )
            }
        )
        history: tuple[Artifact, ...] = (unsealed, retired)
    elif fault == "duplicate":
        history = (retired, retired)
    elif fault == "cycle":
        history = (_progress(retired.artifact_id, supersedes=retired.artifact_id),)
    else:
        plan = seal_artifact(make_plan_artifact(), validated_at=NOW)
        history = (_progress(retired.artifact_id, supersedes=plan.artifact_id), plan)
    with pytest.raises(ArtifactOrderingError):
        latest_accepted_artifact(
            history,
            CoderProgressArtifact,
            excluded_artifact_ids=frozenset((retired.artifact_id,)),
        )
