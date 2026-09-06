"""Deterministic context-only view of an immutable project discovery record."""

import json

from ai_software_engineer.context.models import ContextSource
from ai_software_engineer.domain.model import WirePayload
from ai_software_engineer.project_profile import ProjectProfile


def project_profile_context(profile: ProjectProfile) -> ContextSource:
    """Retain native rules and provenance without repeating every language marker."""
    payload: WirePayload = profile.to_wire()
    payload["kind"] = "project_profile_context"
    payload["languages"] = [
        {
            "language": fact.language.value,
            "marker_count": len(fact.markers),
            "marker_samples": [marker for marker in sorted(fact.markers)[:3]],
        }
        for fact in profile.languages
    ]
    return ContextSource(
        source_id="project.profile",
        uri=f"profile://{profile.project_id}/{profile.profile_sha256}",
        content=json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
        priority=20,
        required=True,
    )
