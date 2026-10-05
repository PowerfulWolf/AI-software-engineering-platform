"""Publication facts select current work without trusting provider clocks or UUIDs."""

from datetime import datetime, timedelta
from typing import cast

import pytest

from ai_software_engineer.artifacts import seal_artifact
from ai_software_engineer.artifacts.ordering import (
    ArtifactOrderingError,
    compare_artifact_order,
    latest_accepted_artifact,
)
from ai_software_engineer.domain.artifact import Artifact, ImplementationReportArtifact
from ai_software_engineer.orchestration.retry import _active_progress
from tests.domain.factories import (
    NOW,
    make_coder_progress_artifact,
    make_implementation_artifact,
    make_qa_artifact,
)


def _implementation(
    identity: str,
    *,
    sealed_at: datetime = NOW,
    provider_at: datetime = NOW,
    supersedes: str | None = None,
    parents: tuple[str, ...] = (),
) -> ImplementationReportArtifact:
    return cast(
        ImplementationReportArtifact,
        seal_artifact(
            make_implementation_artifact().model_copy(
                update={
                    "artifact_id": identity,
                    "created_at": provider_at,
                    "supersedes": supersedes,
                    "parent_artifact_ids": parents,
                }
            ),
            validated_at=sealed_at,
        ),
    )


def test_later_store_seal_wins_over_forged_provider_clock_and_identity() -> None:
    old = _implementation("art_impl_z_old", provider_at=NOW + timedelta(days=100))
    new = _implementation(
        "art_impl_a_new",
        sealed_at=NOW + timedelta(seconds=1),
        provider_at=NOW - timedelta(days=100),
    )
    assert latest_accepted_artifact((new, old), ImplementationReportArtifact) == new


def test_verified_common_stream_wins_even_when_platform_clocks_move_backwards() -> None:
    old = _implementation("art_impl_z_old", sealed_at=NOW + timedelta(hours=1))
    new = _implementation("art_impl_a_new")
    positions = {old.artifact_id: ("claims", 7, 0), new.artifact_id: ("claims", 8, 0)}
    assert (
        latest_accepted_artifact((new, old), ImplementationReportArtifact, trusted_order=positions)
        == new
    )


def test_different_durable_namespaces_cannot_compare_their_sequence_numbers() -> None:
    left = _implementation("art_impl_left")
    right = _implementation("art_impl_right")
    positions = {left.artifact_id: ("state", 100, 0), right.artifact_id: ("claims", 1, 0)}
    assert compare_artifact_order(left, right, trusted_order=positions) is None
    with pytest.raises(ArtifactOrderingError, match="no unique latest"):
        latest_accepted_artifact(
            (left, right), ImplementationReportArtifact, trusted_order=positions
        )


@pytest.mark.parametrize("direct", [False, True])
def test_same_seal_uses_full_supersedes_or_transitive_feedback_lineage(direct: bool) -> None:
    old = _implementation("art_impl_z_old", provider_at=NOW + timedelta(days=100))
    qa = seal_artifact(
        make_qa_artifact().model_copy(update={"parent_artifact_ids": (old.artifact_id,)}),
        validated_at=NOW,
    )
    new = _implementation(
        "art_impl_a_new",
        provider_at=NOW - timedelta(days=100),
        supersedes=old.artifact_id if direct else None,
        parents=() if direct else (qa.artifact_id,),
    )
    artifacts: tuple[Artifact, ...] = (new, qa, old)
    assert compare_artifact_order(new, old, artifacts=artifacts) == 1
    assert latest_accepted_artifact(artifacts, ImplementationReportArtifact) == new


def test_unlinked_same_seal_is_rejected_instead_of_guessing_by_identifier() -> None:
    old = _implementation("art_impl_a_old")
    new = _implementation("art_impl_z_new")
    with pytest.raises(ArtifactOrderingError, match="no unique latest"):
        latest_accepted_artifact((old, new), ImplementationReportArtifact)


@pytest.mark.parametrize("fault", ["duplicate", "cycle", "ancestor_cycle"])
def test_duplicate_identity_and_cycle_are_not_current_work(fault: str) -> None:
    old = _implementation("art_impl_old")
    if fault == "duplicate":
        history: tuple[Artifact, ...] = (old, old)
    elif fault == "cycle":
        other = _implementation("art_impl_other", supersedes=old.artifact_id)
        old = _implementation(old.artifact_id, supersedes=other.artifact_id)
        history = (old, other)
    else:
        qa = seal_artifact(
            make_qa_artifact().model_copy(update={"parent_artifact_ids": ("art_qa_001",)}),
            validated_at=NOW,
        )
        history = (old, qa)
    with pytest.raises(ArtifactOrderingError, match=r"duplicate|cycle"):
        latest_accepted_artifact(history, ImplementationReportArtifact)


def test_single_unsealed_artifact_cannot_become_current() -> None:
    report = make_implementation_artifact()
    report = report.model_copy(
        update={
            "integrity": report.integrity.model_copy(
                update={"validated": False, "validated_at": None}
            )
        }
    )
    with pytest.raises(ArtifactOrderingError, match="platform-sealed"):
        latest_accepted_artifact((report,), ImplementationReportArtifact)


@pytest.mark.parametrize("progress_is_later", [False, True])
def test_active_progress_uses_complete_publication_lineage(progress_is_later: bool) -> None:
    candidate = _implementation("art_impl_accepted", provider_at=NOW + timedelta(days=100))
    progress = seal_artifact(
        make_coder_progress_artifact().model_copy(
            update={
                "created_at": NOW - timedelta(days=100),
                "parent_artifact_ids": (candidate.artifact_id,) if progress_is_later else (),
            }
        ),
        validated_at=NOW,
    )
    from ai_software_engineer.domain.artifact import CoderProgressArtifact

    assert isinstance(progress, CoderProgressArtifact)
    if not progress_is_later:
        candidate = _implementation(candidate.artifact_id, parents=(progress.artifact_id,))
    assert _active_progress(progress, candidate, (progress, candidate)) == (
        progress if progress_is_later else None
    )
