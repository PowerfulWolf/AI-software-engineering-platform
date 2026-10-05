"""Choose accepted lineage with trusted publication facts, never provider clocks or UUIDs."""

from collections.abc import Mapping

from ai_software_engineer.domain.artifact import Artifact

type ArtifactOrderPosition = tuple[str, int, int]


class ArtifactOrderingError(ValueError):
    """Accepted artifacts lack an unambiguous, verifiable publication order."""


def _descends(identity: str, ancestor: str, artifacts: Mapping[str, Artifact]) -> bool:
    current = artifacts.get(identity)
    if current is None:
        return False
    pending = list(current.parent_artifact_ids)
    if current.supersedes is not None:
        pending.append(current.supersedes)
    seen: set[str] = set()
    while pending:
        value = pending.pop()
        if value == ancestor:
            return True
        if value in seen:
            continue
        seen.add(value)
        parent = artifacts.get(value)
        if parent is not None:
            pending.extend(parent.parent_artifact_ids)
            if parent.supersedes is not None:
                pending.append(parent.supersedes)
    return False


def compare_artifact_order(
    left: Artifact,
    right: Artifact,
    *,
    artifacts: tuple[Artifact, ...] = (),
    trusted_order: Mapping[str, ArtifactOrderPosition] | None = None,
) -> int | None:
    """Return accepted order, or None when no trusted fact distinguishes the pair.

    Only a common durable stream namespace makes sequence/ordinal comparable.
    Platform seal time is the legacy publication fact. Equal seal time requires
    explicit parent/supersedes lineage; provider created_at and identity text carry
    no authority to determine the current implementation or verdict.
    """
    if left.task_id != right.task_id:
        raise ArtifactOrderingError("artifact ordering cannot cross Task identities")
    left_sealed_at = left.integrity.validated_at
    right_sealed_at = right.integrity.validated_at
    if (
        not left.integrity.validated
        or not right.integrity.validated
        or left_sealed_at is None
        or right_sealed_at is None
    ):
        raise ArtifactOrderingError("artifact ordering requires platform-sealed integrity")
    if left.artifact_id == right.artifact_id:
        if left != right:
            raise ArtifactOrderingError("an artifact identity has conflicting immutable facts")
        return 0
    if trusted_order is not None:
        left_position = trusted_order.get(left.artifact_id)
        right_position = trusted_order.get(right.artifact_id)
        if (
            left_position is not None
            and right_position is not None
            and left_position[0] == right_position[0]
            and left_position[1:] != right_position[1:]
        ):
            return 1 if left_position[1:] > right_position[1:] else -1
    if left_sealed_at != right_sealed_at:
        return 1 if left_sealed_at > right_sealed_at else -1
    by_id = {artifact.artifact_id: artifact for artifact in (*artifacts, left, right)}
    left_descends = _descends(left.artifact_id, right.artifact_id, by_id)
    right_descends = _descends(right.artifact_id, left.artifact_id, by_id)
    if left_descends and right_descends:
        raise ArtifactOrderingError("accepted artifact lineage contains a cycle")
    if left_descends:
        return 1
    if right_descends:
        return -1
    return None


def latest_accepted_artifact[ArtifactT: Artifact](
    artifacts: tuple[Artifact, ...],
    artifact_type: type[ArtifactT],
    *,
    trusted_order: Mapping[str, ArtifactOrderPosition] | None = None,
) -> ArtifactT | None:
    candidates = tuple(artifact for artifact in artifacts if isinstance(artifact, artifact_type))
    if not candidates:
        return None
    if any(
        not artifact.integrity.validated or artifact.integrity.validated_at is None
        for artifact in artifacts
    ):
        raise ArtifactOrderingError("artifact ordering requires platform-sealed integrity")
    by_id = {artifact.artifact_id: artifact for artifact in artifacts}
    if len(by_id) != len(artifacts):
        raise ArtifactOrderingError("accepted artifact history contains duplicate identities")
    if any(_descends(artifact.artifact_id, artifact.artifact_id, by_id) for artifact in artifacts):
        raise ArtifactOrderingError("accepted artifact lineage contains a cycle")
    maximal = tuple(
        artifact
        for artifact in candidates
        if not any(
            compare_artifact_order(
                other, artifact, artifacts=artifacts, trusted_order=trusted_order
            )
            == 1
            for other in candidates
            if other is not artifact
        )
    )
    if len(maximal) != 1:
        raise ArtifactOrderingError(
            "accepted artifacts have no unique latest publication or lineage"
        )
    return maximal[0]
