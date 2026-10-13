"""Verified Requirement exclusions for ordinary Operation reads, never execution authority."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Protocol

from ai_software_engineer.manager.delivery import _delivery_id
from ai_software_engineer.multi_directory.production import DerivedStageInputs
from ai_software_engineer.multi_directory.retirement import RequirementRetirementStore
from ai_software_engineer.multi_directory.store import JointJournal
from ai_software_engineer.project_workspace import ProjectWorkspaceRegistry
from ai_software_engineer.team_workspace import TeamWorkspace


@dataclass(frozen=True)
class RequirementOperationVisibility:
    excluded: frozenset[tuple[str, str]] = frozenset()

    @property
    def sha256(self) -> str:
        return hashlib.sha256(repr(sorted(self.excluded)).encode()).hexdigest()

    def visible(self, project_id: str | None, delivery_id: str | None) -> bool:
        return (project_id, delivery_id) not in self.excluded


class RequirementOperationVisibilityReader(Protocol):
    def read(self) -> RequirementOperationVisibility: ...


class ProductionRequirementOperationVisibility:
    """Revalidate manifests, retirement and complete parent prefixes on every read."""

    def __init__(self, team: TeamWorkspace) -> None:
        self.team = team

    def read(self) -> RequirementOperationVisibility:
        excluded: set[tuple[str, str]] = set()
        for project in ProjectWorkspaceRegistry(self.team).discover():
            journal = JointJournal(project.requirements_root, read_only=True)
            retirements = RequirementRetirementStore(
                project.requirements_root,
                team_id=self.team.manifest.team_id,
                team_manifest_sha256=self.team.manifest.manifest_sha256,
                project_id=project.manifest.project_id,
                project_manifest_sha256=project.manifest.manifest_sha256,
                read_only=True,
            )
            for parent_id in retirements.retired_delivery_ids(journal):
                excluded.add((project.manifest.project_id, parent_id))
                entry = retirements.entry(parent_id)
                assert entry is not None
                completion = retirements.purged_entry(entry)
                if completion is not None:
                    from ai_software_engineer.multi_directory.purge import (
                        RequirementPurgeCompletion,
                    )

                    assert isinstance(completion, RequirementPurgeCompletion)
                    excluded.update(
                        (project.manifest.project_id, child_id)
                        for child_id in completion.native_delivery_ids
                    )
                    continue
                for record in journal.history(parent_id):
                    if (
                        record.team_id,
                        record.team_manifest_sha256,
                        record.project_id,
                        record.project_manifest_sha256,
                    ) != (
                        self.team.manifest.team_id,
                        self.team.manifest.manifest_sha256,
                        project.manifest.project_id,
                        project.manifest.manifest_sha256,
                    ):
                        raise ValueError("retired Requirement historical owner differs")
                    for child in record.children:
                        excluded.add((project.manifest.project_id, child.checkpoint.delivery_id))
                    if record.plan is not None:
                        for unit in record.plan.units:
                            derived = DerivedStageInputs(record, unit.unit_id)
                            excluded.add(
                                (
                                    project.manifest.project_id,
                                    _delivery_id(
                                        derived.root,
                                        derived.requirement,
                                        namespace=record.project_id,
                                    ),
                                )
                            )
        return RequirementOperationVisibility(frozenset(excluded))
