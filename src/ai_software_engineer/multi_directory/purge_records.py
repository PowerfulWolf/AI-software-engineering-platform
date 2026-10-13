"""Read actual sealed delivery records before accepting deletion ownership."""

import json
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .purge_state import StateDeletionScope

from ai_software_engineer.domain.model import WirePayload
from ai_software_engineer.safe_files import _read_regular


def verified_record(
    path: Path, sidecar: Path, payload: WirePayload, expected: "StateDeletionScope"
) -> WirePayload:
    from .purge_state import validate_declared_scopes

    namespace = path.relative_to(sidecar).parts[0]
    if namespace == "artifacts":
        from ai_software_engineer.artifacts.store import FileArtifactStore

        return FileArtifactStore(sidecar / namespace, read_only=True).get(path.stem).to_wire()
    if namespace == "contexts":
        from ai_software_engineer.context.store import FileContextStore

        return FileContextStore(sidecar / namespace, read_only=True).get(path.stem).to_wire()
    if namespace == "evaluations":
        from ai_software_engineer.evaluation.store import FileEvaluationEventStore

        return (
            FileEvaluationEventStore(sidecar / namespace, read_only=True).get(path.stem).to_wire()
        )
    if namespace == "evidence":
        from ai_software_engineer.evidence.models import validate_evidence_record

        record = validate_evidence_record(payload)
        record.validate_integrity()
        validate_declared_scopes(record.to_wire(), expected)
        if record.evidence_id != path.stem:
            raise ValueError("evidence index differs")
        return record.to_wire()
    if namespace == "runs":
        if path.is_relative_to(sidecar / "runs/model-routes"):
            from ai_software_engineer.agents.fallback import FileModelRouteAttemptStore

            route = FileModelRouteAttemptStore._read(path)
            if path.parent.name != route.run_id:
                raise ValueError("model route Run index differs")
            return route.to_wire()
        from ai_software_engineer.evidence.models import (
            RunEvidenceManifest,
            validate_evidence_record,
        )

        manifest = RunEvidenceManifest.model_validate(payload)
        manifest.validate_integrity()
        validate_declared_scopes(manifest.to_wire(), expected)
        if manifest.identity.run_id != path.stem:
            raise ValueError("Run index differs")
        evidence = []
        for item in sorted((sidecar / "evidence").glob("ev_*.json")):
            record = validate_evidence_record(json.loads(_read_regular(item, 64 * 1024 * 1024)))
            record.validate_integrity()
            if record.evidence_id != item.stem:
                raise ValueError("evidence index differs")
            if record.identity.run_id == manifest.identity.run_id:
                if record.identity != manifest.identity:
                    raise ValueError("Run evidence owner differs")
                evidence.append(record)
        evidence.sort(key=lambda value: (value.captured_at, value.evidence_id))
        if tuple(record.evidence_id for record in evidence) != manifest.evidence_ids:
            raise ValueError("Run evidence closure differs")
        return manifest.to_wire()
    if namespace == "handoffs":
        from ai_software_engineer.evaluation.handoff import (
            HandoffBundle,
            handoff_identity,
            render_handoff_markdown,
        )

        bundle = HandoffBundle.model_validate(payload)
        validate_declared_scopes(bundle.to_wire(), expected)
        if bundle.handoff_id != path.stem or handoff_identity(bundle) != path.stem:
            raise ValueError("handoff identity differs")
        if _read_regular(
            path.with_suffix(".md"), 64 * 1024 * 1024
        ).decode() != render_handoff_markdown(bundle):
            raise ValueError("handoff Markdown differs")
        return bundle.to_wire()
    # State records have their own indexed envelope; reject unrecognized ownership
    # rather than treating JSON owner text as deletion authority.
    from ai_software_engineer.multi_directory.purge_state import verified_state_record

    return verified_state_record(path, sidecar, payload, expected)
