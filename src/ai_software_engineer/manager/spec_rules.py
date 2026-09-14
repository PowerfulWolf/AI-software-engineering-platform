"""Compile active Team/Project Spec documents into provenance-bound rules."""

from __future__ import annotations

from dataclasses import dataclass

from ai_software_engineer.repository_profile import RepositoryProfile
from ai_software_engineer.spec_compiler import SpecRule, SpecRuleLayer, SpecSourceRef
from ai_software_engineer.spec_documents import SpecDocument


def team_spec_rules(specs: tuple[SpecDocument, ...]) -> tuple[SpecRule, ...]:
    """Convert the exact active Team Spec snapshot into platform engineering rules."""
    return tuple(
        _rule(spec, layer=SpecRuleLayer.PLATFORM_ENGINEERING)
        for spec in specs
        if spec.scope == "team"
    )


@dataclass(frozen=True, slots=True)
class ProductionProjectRuleProvider:
    """ProjectRuleProvider backed by one immutable active Project Spec snapshot."""

    specs: tuple[SpecDocument, ...]

    def rules_for(self, profile: RepositoryProfile) -> tuple[SpecRule, ...]:
        return tuple(
            _rule(spec, layer=SpecRuleLayer.PROJECT, repository_id=str(profile.repository_id))
            for spec in self._applicable(profile)
        )

    def sources_for(self, profile: RepositoryProfile) -> tuple[SpecSourceRef, ...]:
        return tuple(
            SpecSourceRef(
                uri=_project_uri(str(profile.repository_id), spec),
                sha256=spec.spec_sha256,
            )
            for spec in self._applicable(profile)
        )

    def _applicable(self, profile: RepositoryProfile) -> tuple[SpecDocument, ...]:
        return tuple(
            spec
            for spec in self.specs
            if spec.scope == "project"
            and (spec.applies_to_all_repositories or profile.repository_id in spec.repository_ids)
        )


def _rule(
    spec: SpecDocument,
    *,
    layer: SpecRuleLayer,
    repository_id: str | None = None,
) -> SpecRule:
    source_uri = (
        f"platform://team/{spec.team_id}/specs/{spec.spec_id}"
        if layer is SpecRuleLayer.PLATFORM_ENGINEERING
        else _project_uri(repository_id or "", spec)
    )
    return SpecRule(
        id=f"rule_spec_{spec.spec_id.removeprefix('spec_document_')}",
        field=f"governance.{spec.spec_key}",
        value={
            "spec_id": spec.spec_id,
            "spec_key": spec.spec_key,
            "version": spec.version,
            "title": spec.title,
            "body_markdown": spec.body_markdown,
            "roles": [role.value for role in spec.roles],
            "stages": list(spec.stages),
            "repository_ids": list(spec.repository_ids),
            "path_globs": list(spec.path_globs),
            "verification": spec.verification,
        },
        layer=layer,
        priority=100,
        scopes=("*",),
        source_uri=source_uri,
        source_sha256=spec.spec_sha256,
        rationale="Active, human-authored engineering Spec; compliance is mandatory.",
    )


def _project_uri(repository_id: str, spec: SpecDocument) -> str:
    return f"project://{repository_id}/.ase/specs/{spec.spec_id}"


__all__ = ["ProductionProjectRuleProvider", "team_spec_rules"]
