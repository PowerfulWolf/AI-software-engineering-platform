"""Approved knowledge remains visible after reopening, without advancing delivery."""

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator

from ai_software_engineer.config import ModelProviderKind, ProductionConfig, ProviderRouteConfig
from ai_software_engineer.domain.enums import TeamRole
from ai_software_engineer.knowledge.gaps import KnowledgeGapService
from ai_software_engineer.knowledge.models import (
    KnowledgeError,
    KnowledgeSearchRequest,
    digest,
    text_digest,
)
from ai_software_engineer.knowledge.retrieval import MarkdownKnowledgeRetrieval
from ai_software_engineer.knowledge.skills import KnowledgeSkillRegistry
from ai_software_engineer.knowledge.stages import _snapshot
from ai_software_engineer.knowledge.store import KnowledgeRecordStore
from ai_software_engineer.multi_directory.models import JointCheckpoint, JointStage
from ai_software_engineer.team_view.models import ScopeView, TaskView, TeamSnapshot
from ai_software_engineer.team_view.reader import ProductionTeamReader, _request_with_current_work
from ai_software_engineer.web_console import (
    CreateRequirementIntent,
    LocalConsoleAdministration,
    create_console_app,
)
from tests.knowledge.test_retrieval_contract import binding
from tests.manager.test_directory_scope import repository
from tests.team_view.test_live import _bytes
from tests.web_console.test_git_baseline import _console
from tests.web_console.test_transport import _Console


@pytest.mark.parametrize("repository_owned", [False, True])
def test_approved_gap_survives_reopened_api_and_read_only_snapshot(
    tmp_path: Path, repository_owned: bool
) -> None:
    code = repository(tmp_path / "code")
    console, entry = _console(tmp_path)
    console.submit(
        CreateRequirementIntent(
            project_id="project_test", name="Settings", repository_roots=(str(code),)
        ),
        idempotency_key="create-gap",
    )
    created = console.run_once()
    assert created is not None and created.result is not None
    assert created.result.delivery_id is not None
    cp = entry.journal.current(created.result.delivery_id)
    assert cp is not None
    root = entry.journal.directory(cp.delivery_id) / "knowledge"
    if repository_owned:
        root = (
            entry.project.root
            / "repositories"
            / cp.preparations[0].result.repository_id
            / "knowledge"
            / "runs"
        )
    records = KnowledgeRecordStore(root)
    frozen = _snapshot(cp)
    bound = binding(frozen, TeamRole.PRODUCT)
    skills = KnowledgeSkillRegistry(bound, frozen, MarkdownKnowledgeRetrieval(), records)
    skills.search_knowledge(
        KnowledgeSearchRequest(operation_id="scope_question", binding=bound, query="account")
    )
    gap = KnowledgeGapService(records).report(
        manifest=skills.manifest(),
        question="Keep the single-account action?",
        required_decision="Confirm scope",
        reason="MISSING",
        severity="BLOCKING",
        impact="Cannot continue",
        risk="high",
    )
    waiting = JointCheckpoint.seal(
        {
            **cp.to_wire(),
            "sequence": cp.sequence + 1,
            "previous_checkpoint_sha256": cp.checkpoint_sha256,
            "stage": JointStage.WAITING_HUMAN,
            "knowledge_gap_id": gap.gap_id,
            "knowledge_wait_stage": JointStage.PRODUCT_DISCOVERY,
            "next_action": f"Resolve and approve knowledge gap {gap.gap_id} before resuming.",
        }
    )
    entry.journal.append(waiting, expected=cp.checkpoint_sha256)
    config = ProductionConfig(
        platform_root=str(tmp_path / "platform"),
        model_routes=(
            ProviderRouteConfig(provider="codex", model="test", kind=ModelProviderKind.CODEX_CLI),
        ),
    )
    reader = ProductionTeamReader(config, {})

    def client() -> TestClient:
        administration = LocalConsoleAdministration(
            runtime_config=config, config_path=tmp_path / "config.json", environment={}
        )
        return TestClient(
            create_console_app(
                _Console(),
                reader,
                team_id=config.team_id,
                administration=administration,
            ),
            base_url="http://127.0.0.1:8765",
        )

    base = f"/api/v1/admin/projects/project_test/requirements/{cp.delivery_id}"
    pending = client().get(base + "/knowledge-gaps")
    assert pending.status_code == 200
    assert pending.json()[0]["gap"]["gap_id"] == gap.gap_id
    assert pending.json()[0]["is_current"] is True
    assert not pending.json()[0].get("resolution")
    request = reader.snapshot("project_test").requests[0]
    assert request.knowledge_gap is not None and request.knowledge_gap.resolution is None
    assert "补充并批准" in request.next_action
    history = entry.journal.history(cp.delivery_id)
    command = {
        "gap_id": gap.gap_id,
        "answer": "A",
        "sources": [{"uri": "产品确认", "content": "A", "sha256": text_digest("A")}],
        "approval_reference": "local-console:" + gap.gap_id,
    }
    approved = client().post(base + "/knowledge-resolutions", json=command)
    assert approved.status_code == 201, approved.text
    before = _bytes(tmp_path / "platform")
    read_only = KnowledgeRecordStore(root, read_only=True)
    with pytest.raises(KnowledgeError, match="STORE_READ_ONLY"):
        read_only.put("gaps", gap.gap_id, gap)
    reopened = client().get(base + "/knowledge-gaps")
    assert reopened.status_code == 200
    assert reopened.json()[0]["resolution"] == approved.json()
    snapshot = reader.snapshot("project_test")
    request = snapshot.requests[0]
    assert request.stage == "WAITING_HUMAN"  # No delivery state migration on approval or GET.
    assert request.checkpoint_sha256 == waiting.checkpoint_sha256
    assert request.knowledge_gap is not None and request.knowledge_gap.resolution is not None
    assert request.knowledge_gap.resolution.answer == "A"
    assert "无需重复解答" in request.next_action
    child = TaskView(
        id="delivery_child",
        project_id="project_test",
        request_id=request.id,
        title="Preserved checkpoint",
        scope=ScopeView(root=str(code), selected_paths=(".",)),
        status="IMPLEMENTING",
        checkpoint_stage="DELIVERING",
        terminal=False,
        last_activity=datetime.now(UTC),
        next_action="RUN_DELIVERY",
    )
    assert _request_with_current_work(request, [child]) == request
    schema = json.loads(
        (Path(__file__).parents[2] / "schemas/team-snapshot.schema.json").read_text()
    )
    assert {key: value for key, value in schema.items() if key not in {"$id", "$schema"}} == (
        TeamSnapshot.model_json_schema()
    )
    Draft202012Validator(schema).validate(snapshot.to_wire())
    assert _bytes(tmp_path / "platform") == before
    assert entry.journal.history(cp.delivery_id) == history
    assert client().post(base + "/knowledge-resolutions", json=command).status_code == 201
    assert (
        client().post(base + "/knowledge-resolutions", json={**command, "answer": "B"}).status_code
        == 409
    )
    assert (
        client().get(base.replace("project_test", "project_other") + "/knowledge-gaps").status_code
        == 404
    )

    # A new current gap must not make the historical approved gap actionable again.
    new_gap = KnowledgeGapService(records).report(
        manifest=skills.manifest(),
        question="Which icon?",
        required_decision="Confirm icon",
        reason="MISSING",
        severity="BLOCKING",
        impact="Cannot continue",
        risk="high",
    )
    next_cp = JointCheckpoint.seal(
        {
            **waiting.to_wire(),
            "sequence": waiting.sequence + 1,
            "previous_checkpoint_sha256": waiting.checkpoint_sha256,
            "knowledge_gap_id": new_gap.gap_id,
        }
    )
    entry.journal.append(next_cp, expected=waiting.checkpoint_sha256)
    values = {v["gap"]["gap_id"]: v for v in client().get(base + "/knowledge-gaps").json()}
    assert values[gap.gap_id]["is_current"] is False
    assert values[gap.gap_id]["resolution"]["answer"] == "A"
    assert values[new_gap.gap_id]["is_current"] is True
    assert client().post(base + "/knowledge-resolutions", json=command).status_code == 409

    # A valid envelope cannot make a foreign run resolution an approval for this gap.
    resolution_path = root / records._name("gap-resolutions", new_gap.gap_id)
    forged = {**approved.json(), "gap_id": new_gap.gap_id, "previous_run_id": "run_foreign"}
    forged["resolution_id"] = digest({k: v for k, v in forged.items() if k != "resolution_id"})
    resolution_path.write_text(json.dumps({"record": forged, "sha256": digest(forged)}))
    assert client().get(base + "/knowledge-gaps").status_code == 404
    assert client().get("/api/v1/team?project_id=project_test").status_code == 503


def test_read_only_knowledge_store_never_creates_missing_directory(tmp_path: Path) -> None:
    root = tmp_path / "missing" / "knowledge"
    with pytest.raises(KnowledgeError, match="STORE_PATH"):
        KnowledgeRecordStore(root, read_only=True)
    assert not root.parent.exists()
