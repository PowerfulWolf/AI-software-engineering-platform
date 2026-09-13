"""Knowledge selections are scope-bound, atomic, and live-readable."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ai_software_engineer.knowledge_documents import (
    ProjectKnowledgeDocumentStore,
    TeamKnowledgeDocumentStore,
)
from ai_software_engineer.knowledge_selection import (
    KnowledgeSelectionError,
    ProjectKnowledgeSelectionStore,
    TeamKnowledgeSelectionStore,
    effective_project_knowledge_paths,
    effective_team_knowledge_paths,
)
from ai_software_engineer.team_workspace import TeamWorkspace


def test_team_and_project_selections_are_independent(tmp_path: Path) -> None:
    team = TeamWorkspace.initialize(tmp_path / "platform", team_id="team_test", name="Test")
    project = team.project_registry().register(project_id="project_test", name="Project")
    team_document = TeamKnowledgeDocumentStore(team).import_document(
        filename="team.md", content=b"# Team\n"
    )
    project_document = ProjectKnowledgeDocumentStore(project).import_document(
        filename="project.md", content=b"# Project\n"
    )

    assert effective_team_knowledge_paths(team, ("fallback.md",)) == ("fallback.md",)
    assert effective_project_knowledge_paths(project, ("fallback.md",)) == ("fallback.md",)
    team_selection = TeamKnowledgeSelectionStore(team).save(
        (team_document.normalized_relative_path,)
    )
    project_selection = ProjectKnowledgeSelectionStore(project).save(
        (project_document.normalized_relative_path,)
    )

    assert effective_team_knowledge_paths(team) == team_selection.selected_paths
    assert effective_project_knowledge_paths(project) == project_selection.selected_paths
    assert TeamKnowledgeSelectionStore(team).save(team_selection.selected_paths) == (team_selection)


def test_resealed_selection_cannot_move_between_projects(tmp_path: Path) -> None:
    team = TeamWorkspace.initialize(tmp_path / "platform", team_id="team_test", name="Test")
    first = team.project_registry().register(project_id="project_first", name="First")
    second = team.project_registry().register(project_id="project_second", name="Second")
    document = ProjectKnowledgeDocumentStore(first).import_document(
        filename="guide.md", content=b"# Guide\n"
    )
    selection = ProjectKnowledgeSelectionStore(first).save((document.normalized_relative_path,))
    target = ProjectKnowledgeSelectionStore(second).path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(selection.to_wire()), encoding="utf-8")

    with pytest.raises(KnowledgeSelectionError, match="identity mismatch"):
        ProjectKnowledgeSelectionStore(second).load()
