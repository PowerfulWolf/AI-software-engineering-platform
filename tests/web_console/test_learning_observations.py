"""Actual administration endpoints preserve pending learning and publication boundaries."""

from pathlib import Path

from fastapi.testclient import TestClient

from ai_software_engineer.artifacts import FileArtifactStore, seal_artifact
from ai_software_engineer.config import ProductionConfig
from ai_software_engineer.domain.artifact import ProjectObservation
from ai_software_engineer.knowledge_selection import effective_project_knowledge_paths
from ai_software_engineer.team_workspace import TeamWorkspace
from ai_software_engineer.web_console import LocalConsoleAdministration, create_console_app
from tests.domain.factories import NOW, make_implementation_artifact, make_plan_artifact
from tests.web_console.test_transport import _Console, _Reader


def test_learning_collection_approval_and_background_display_through_http(tmp_path: Path) -> None:
    config = ProductionConfig.model_validate(
        {
            "platform_root": str(tmp_path / "platform"),
            "team_id": "team_test",
            "team_name": "Team",
            "model_routes": [{"provider": "codex", "model": "fixture", "kind": "codex_cli"}],
        }
    )
    team = TeamWorkspace.initialize(
        config.platform_root, team_id=config.team_id, name=config.team_name
    )
    project = team.project_registry().register(project_id="project_web", name="Web")
    code = tmp_path / "code"
    code.mkdir()
    repository = project.repository_registry().register(code)
    artifacts = FileArtifactStore(repository.directory("artifacts"))
    artifacts.put(seal_artifact(make_plan_artifact(), validated_at=NOW))
    implementation = make_implementation_artifact()
    artifacts.put(
        seal_artifact(
            implementation.model_copy(
                update={
                    "content": implementation.content.model_copy(
                        update={
                            "project_observations": (
                                ProjectObservation(
                                    observation_id="refund_identity",
                                    title="Refund identity",
                                    fact="Refunds use the original payment ID.",
                                    applicability="This repository only.",
                                    evidence_ids=(implementation.evidence[0].evidence_id,),
                                ),
                            )
                        }
                    )
                }
            ),
            validated_at=NOW,
        )
    )
    administration = LocalConsoleAdministration(
        runtime_config=config,
        config_path=tmp_path / "config.json",
        environment={},
        mysql_probe=lambda _: None,
    )
    app = create_console_app(
        _Console(), _Reader(), team_id=config.team_id, port=8765, administration=administration
    )
    endpoint = "/api/v1/admin/projects/project_web/learnings"
    with TestClient(app, base_url="http://127.0.0.1:8765") as client:
        assert client.get(endpoint).json() == []  # GET must not collect or mutate.
        collected = client.post(endpoint + "/collect")
        assert collected.status_code == 200
        proposal = collected.json()[0]["proposal"]
        assert proposal["trigger"] == "PROJECT_OBSERVATION"
        assert proposal["evidence"][0]["source_revision"] == implementation.source_revision
        assert effective_project_knowledge_paths(project) == ()
        assert client.post(endpoint + "/collect").json() == collected.json()
        decision = {
            "proposal_sha256": "0" * 64,
            "action": "APPROVE",
            "target": "KNOWLEDGE",
            "operator_id": "local-human",
            "rationale": "Confirm this scoped fact.",
        }
        decision_endpoint = endpoint + "/" + proposal["proposal_id"] + "/decision"
        assert client.post(decision_endpoint, json=decision).status_code == 409
        assert effective_project_knowledge_paths(project) == ()
        decision["proposal_sha256"] = proposal["proposal_sha256"]
        approved = client.post(decision_endpoint, json=decision)
        assert approved.status_code == 200
        assert approved.json()["decision"]["published_uri"].startswith("project://project_web/")
        assert client.get(endpoint).json()[0]["decision"] == approved.json()["decision"]
        administration.tick_knowledge_indexes()
        sources = project.knowledge_sources(effective_project_knowledge_paths(project))
        assert len(sources) == 1 and "original payment ID" in (sources[0].content or "")
        knowledge = client.get("/api/v1/admin/projects/project_web/knowledge")
        assert knowledge.status_code == 200 and len(knowledge.json()) == 1
