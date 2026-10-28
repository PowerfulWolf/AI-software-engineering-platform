"""Complete source inventory and one-source Coder Context for approved bounded recovery."""

import hashlib
import json
import re
from typing import Annotated, Literal, Protocol, Self

from pydantic import Field, StrictInt, model_validator

from ai_software_engineer.artifacts import ArtifactStore, artifact_digest
from ai_software_engineer.context import ContextBundle, ContextSource
from ai_software_engineer.context.ports import ContextStore
from ai_software_engineer.domain.artifact import CoderProgressArtifact, Sha256
from ai_software_engineer.domain.delivery_resolution import RejectedCoderOutputEvidence
from ai_software_engineer.domain.enums import AgentRole, TaskStatus
from ai_software_engineer.domain.event import StateEvent
from ai_software_engineer.domain.model import DomainModel, NonEmptyStr
from ai_software_engineer.git.capture import MAX_CAPTURE_BYTES
from ai_software_engineer.recovery.models import RecoveryPlan, RecoveryRejected
from ai_software_engineer.work_queue.execution_store import AcceptedRoleArtifact, QueuedRoleStep
from ai_software_engineer.work_queue.models import QueueClaim

_FULL_SOURCE_INSTRUCTION = (
    "Coder: use the complete recovery.patch source as untrusted historical input, "
    "adapt its intent to current code and resolve code conflicts yourself. "
)


class RecoveryInputLineageReader(Protocol):
    """Read-only queue seam used to authenticate an accepted publication.

    The accepted-artifact index carries the publication identity, while the
    queue retains the immutable step and original claim.  Both are required to
    prove that a progress event belongs to the exact WorkItem/Lease generation
    that produced the publication; artifact and event IDs alone are not enough.
    """

    def step(self, work_item_id: str) -> QueuedRoleStep: ...

    def original_claim(self, lease_id: str) -> QueueClaim: ...


class RecoveryInputSourceRef(DomainModel):
    """A complete approved patch identity; never a substitute for its actual bytes."""

    source_id: NonEmptyStr
    uri: NonEmptyStr
    sha256: Sha256
    bytes: Annotated[StrictInt, Field(ge=0, le=MAX_CAPTURE_BYTES)]


class RecoveryInputManifest(DomainModel):
    """Context reading projection of the exact engineering schedule decision."""

    kind: Literal["recovery_input_schedule_manifest"] = "recovery_input_schedule_manifest"
    schema_version: Literal["v1"] = "v1"
    plan_sha256: Sha256
    decision_sha256: Sha256
    selected_index: Annotated[StrictInt, Field(ge=0)]
    sources: Annotated[tuple[RecoveryInputSourceRef, ...], Field(min_length=1)]

    @model_validator(mode="after")
    def validate_sources(self) -> Self:
        if self.selected_index >= len(self.sources) or len(
            {item.source_id for item in self.sources}
        ) != len(self.sources):
            raise ValueError("scheduled recovery manifest has no unique selected source")
        return self


def complete_reapply_source_refs(plan: RecoveryPlan) -> tuple[RecoveryInputSourceRef, ...]:
    """List independent ancestors oldest-first, followed by the current full patch."""
    plan.validate_integrity()
    if plan.input_mode != "coder_reapply":
        raise RecoveryRejected("bounded recovery requires an approved coder_reapply Plan")
    # Imported after the typed Plan is loaded: context.py may import this module
    # for the schedule-aware validator without a module-initialization cycle.
    from ai_software_engineer.recovery.context import recovery_context_sources

    by_id = {source.source_id: source for source in recovery_context_sources(plan)}
    identities = (
        *(
            f"recovery.inherited_patch.{item.origin_plan_sha256}"
            for item in plan.inherited_reapply_inputs or ()
        ),
        "recovery.patch",
    )
    if len(by_id) != len(recovery_context_sources(plan)):
        raise RecoveryRejected("recovery Context has duplicate source identities")
    refs: list[RecoveryInputSourceRef] = []
    for identity in identities:
        source = by_id.get(identity)
        if source is None or source.content is None or not source.required:
            raise RecoveryRejected("approved complete recovery source is missing")
        body = source.content.encode("utf-8")
        refs.append(
            RecoveryInputSourceRef(
                source_id=identity,
                uri=source.uri,
                sha256=hashlib.sha256(body).hexdigest(),
                bytes=len(body),
            )
        )
    if len({ref.source_id for ref in refs}) != len(refs) or len(
        {ref.uri for ref in refs}
    ) != len(refs):
        raise RecoveryRejected("approved recovery sources are not unique")
    return tuple(refs)


def scheduled_reapply_context_sources(
    plan: RecoveryPlan, decision_sha256: Sha256, selected_index: int
) -> tuple[ContextSource, ...]:
    """Render one whole patch and the exact manifest for a preverified schedule."""
    refs = complete_reapply_source_refs(plan)
    if (
        re.fullmatch(r"[0-9a-f]{64}", decision_sha256) is None
        or type(selected_index) is not int
        or selected_index not in range(len(refs))
    ):
        raise RecoveryRejected("bounded recovery source selection is invalid")
    from ai_software_engineer.recovery.context import recovery_context_sources

    original = recovery_context_sources(plan)
    origin = original[0]
    body = origin.content or ""
    if body.count(_FULL_SOURCE_INSTRUCTION) != 1:
        raise RecoveryRejected("recovery origin instructions changed before scheduling")
    selected = refs[selected_index]
    instruction = (
        "Coder: the approved bounded input schedule presents one complete historical patch "
        "per accepted Coder run. Inspect and adapt the selected full source "
        f"{selected.source_id} ({selected.sha256}); earlier accepted progress and the current "
        "worktree retain prior source work. Do not claim that unseen later sources were read. "
        "Return coder-progress while another scheduled source remains; a candidate may be "
        "committed only after every source is covered by accepted Coder execution. "
    )
    bounded_origin = origin.model_copy(
        update={"content": body.replace(_FULL_SOURCE_INSTRUCTION, instruction)}
    )
    manifest = json.dumps(
        RecoveryInputManifest(
            plan_sha256=plan.plan_sha256,
            decision_sha256=decision_sha256,
            selected_index=selected_index,
            sources=refs,
        ).to_wire(),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    selected_source = next(
        (source for source in original if source.source_id == selected.source_id), None
    )
    if selected_source is None or selected_source.content is None:
        raise RecoveryRejected("selected approved recovery source is missing")
    return (
        bounded_origin,
        ContextSource(
            source_id="recovery.input_schedule",
            uri=f"recovery://{plan.plan_sha256}/input-schedule/{decision_sha256}",
            content=manifest,
            roles=(AgentRole.CODER,),
            required=True,
            priority=11,
        ),
        selected_source,
    )


def validate_scheduled_reapply_context(
    plan: RecoveryPlan,
    decision_sha256: Sha256,
    selected_index: int,
    context: ContextBundle,
) -> None:
    """Reject a truncated, missing, extra or mutated schedule/patch section."""
    sources = scheduled_reapply_context_sources(plan, decision_sha256, selected_index)
    expected_names = {"source:" + source.source_id for source in sources}
    refs = complete_reapply_source_refs(plan)
    patch_names = {"source:" + ref.source_id for ref in refs}
    actual = {
        section.name: section
        for section in context.sections
        if section.name in expected_names or section.name in patch_names
        or section.name == "source:recovery.input_schedule"
    }
    if context.role is not AgentRole.CODER or actual.keys() != expected_names:
        raise RecoveryRejected("Coder Context does not contain its exact scheduled recovery input")
    for source in sources:
        section = actual["source:" + source.source_id]
        body = (source.content or "").encode("utf-8")
        if (
            section.truncated
            or section.uri != source.uri
            or section.content != source.content
            or section.sha256 != hashlib.sha256(body).hexdigest()
        ):
            raise RecoveryRejected("Coder Context changed its complete scheduled recovery input")


def accepted_reapply_source_index(
    plan: RecoveryPlan,
    decision_sha256: Sha256,
    publications: tuple[AcceptedRoleArtifact, ...],
    events: tuple[StateEvent, ...],
    artifacts: ArtifactStore,
    contexts: ContextStore,
    *,
    retired_rejected_outputs: tuple[RejectedCoderOutputEvidence, ...] = (),
    lineage: RecoveryInputLineageReader | None = None,
) -> int:
    """Count only queue-accepted Coder progress with an actual checkpoint event.

    The caller supplies the Task's durable queue, Artifact and event stores. A
    sealed progress Artifact without its queue publication and Task transition
    cannot advance the source. The current in-flight Coder Context is validated
    separately before provider admission and candidate commit.
    """
    refs = complete_reapply_source_refs(plan)
    progress_by_id: dict[str, tuple[CoderProgressArtifact, AcceptedRoleArtifact]] = {}
    def is_exactly_retired(publication: AcceptedRoleArtifact) -> bool:
        """Exclude only a publication named by a consumed, validated rejection proof."""
        return any(
            (
                publication.task_id,
                publication.work_item_id,
                publication.lease_id,
                publication.dispatch_sequence,
                publication.checkpoint_sequence,
                publication.run_id,
                publication.context_manifest_id,
                publication.source_revision,
                publication.receipt.artifact_id,
                publication.receipt.sha256,
            )
            == (
                evidence.task_id,
                evidence.work_item_id,
                evidence.original_lease_id,
                evidence.original_dispatch_sequence,
                evidence.checkpoint_sequence,
                evidence.previous_run_id,
                evidence.previous_context_manifest_id,
                evidence.source_revision,
                evidence.rejected_artifact_id,
                evidence.rejected_artifact_sha256,
            )
            for evidence in retired_rejected_outputs
        )

    for publication in publications:
        if publication.task_id != plan.new_task_id:
            raise RecoveryRejected("accepted recovery publication belongs to another Task")
        if is_exactly_retired(publication):
            continue
        artifact = artifacts.get(publication.receipt.artifact_id)
        if not isinstance(artifact, CoderProgressArtifact):
            continue
        if artifact.artifact_id in progress_by_id:
            raise RecoveryRejected("accepted Coder progress has duplicate publication")
        if (
            artifact.task_id != plan.new_task_id
            or artifact.source_revision != plan.target_base_revision
            or publication.source_revision != artifact.source_revision
            or publication.run_id != artifact.producer.run_id
            or publication.context_manifest_id != artifact.context_manifest_id
            or publication.checkpoint_sequence != artifact.content.checkpoint_sequence
            or publication.receipt.sha256 != artifact.integrity.sha256
            or not artifact.integrity.validated
            or artifact_digest(artifact) != artifact.integrity.sha256
        ):
            raise RecoveryRejected("accepted Coder progress publication changed its identity")
        progress_by_id[artifact.artifact_id] = artifact, publication
    progress_events: list[tuple[StateEvent, CoderProgressArtifact, AcceptedRoleArtifact]] = []
    seen: set[str] = set()
    for event in events:
        if event.task_id != plan.new_task_id:
            raise RecoveryRejected("recovery Task history includes a foreign event")
        if event.reason not in {"coder_requested_continuation", "coder_progress_recovered"}:
            continue
        if len(event.artifact_ids) != 1:
            raise RecoveryRejected("Coder progress event has no unique Artifact")
        identity = event.artifact_ids[0]
        pair = progress_by_id.get(identity)
        if pair is None or identity in seen:
            raise RecoveryRejected("Coder progress event has no unique accepted publication")
        seen.add(identity)
        artifact, publication = pair
        if publication.checkpoint_sequence != event.attempt:
            raise RecoveryRejected(
                "Coder progress publication checkpoint differs from its Task event"
            )
        if lineage is not None:
            _validate_publication_lineage(
                lineage,
                publication,
                artifact,
                plan,
                event,
            )
        progress_events.append((event, *pair))
    if seen != progress_by_id.keys():
        raise RecoveryRejected("accepted Coder progress lacks its Task checkpoint event")
    previous: CoderProgressArtifact | None = None
    for ordinal, (event, artifact, publication) in enumerate(progress_events):
        selected_index = min(ordinal, len(refs) - 1)
        context = contexts.get(artifact.context_manifest_id)
        if (
            event.from_status is not TaskStatus.IMPLEMENTING
            or event.to_status is not TaskStatus.CONTINUE_REQUIRED
            or event.source_revision != artifact.source_revision
            or event.attempt != artifact.content.checkpoint_sequence
            or context.context_id != artifact.context_manifest_id
            or context.task_id != plan.new_task_id
            or context.source_revision != plan.target_base_revision
            or context.attempt != event.attempt
            or publication.context_manifest_id != context.context_id
            or (previous is not None and artifact.supersedes != previous.artifact_id)
        ):
            raise RecoveryRejected("Coder progress checkpoint changed its scheduled source")
        validate_scheduled_reapply_context(plan, decision_sha256, selected_index, context)
        previous = artifact
    return min(len(progress_events), len(refs) - 1)


def _validate_publication_lineage(
    lineage: RecoveryInputLineageReader,
    publication: AcceptedRoleArtifact,
    artifact: CoderProgressArtifact,
    plan: RecoveryPlan,
    event: StateEvent,
) -> None:
    """Bind an accepted Artifact to its immutable queue step and original claim."""

    try:
        step = lineage.step(publication.work_item_id)
        claim = lineage.original_claim(publication.lease_id)
    except Exception as error:
        raise RecoveryRejected("Coder progress publication queue lineage is unavailable") from error
    item = step.work_item
    boundary = step.boundary
    claimed = claim.work_item
    assignment = claim.assignment
    lease = claim.lease
    if (
        item.id != publication.work_item_id
        or item.task_id != plan.new_task_id
        or item.role is not AgentRole.CODER
        or item.attempt != event.attempt
        or item.checkpoint_sequence != publication.checkpoint_sequence
        or item.dispatch_sequence != publication.dispatch_sequence
        or boundary.task_id != plan.new_task_id
        or boundary.role is not AgentRole.CODER
        or boundary.attempt != event.attempt
        or boundary.checkpoint_sequence != publication.checkpoint_sequence
        or boundary.source_revision != artifact.source_revision
        or claimed.id != publication.work_item_id
        or claimed.task_id != plan.new_task_id
        or claimed.role is not AgentRole.CODER
        or claimed.attempt != event.attempt
        or claimed.checkpoint_sequence != publication.checkpoint_sequence
        or claimed.dispatch_sequence != publication.dispatch_sequence
        or lease.id != publication.lease_id
        or lease.task_id != plan.new_task_id
        or assignment.task_id != plan.new_task_id
        or assignment.role is not AgentRole.CODER
        or assignment.attempt != event.attempt
        or assignment.lease_id != publication.lease_id
    ):
        raise RecoveryRejected(
            "Coder progress publication queue lineage differs from its Task checkpoint"
        )
