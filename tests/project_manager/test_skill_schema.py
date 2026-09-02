"""Project Manager Agent-visible Skill payloads match their wire Schema."""

import json
from pathlib import Path
from typing import cast

from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource

from ai_software_engineer.domain.model import WirePayload
from ai_software_engineer.project_manager import (
    PrepareProjectRequest,
    ProjectStage,
    StageAdvanceRequest,
)
from tests.project_manager.test_contracts import NOW, stage_chain
from tests.project_manager.test_preparation import service

SCHEMA_DIR = Path(__file__).parents[2] / "schemas"


def _validator() -> Draft202012Validator:
    schemas: list[tuple[str, Resource[object]]] = []
    project_manager_schema: dict[str, object] | None = None
    for path in SCHEMA_DIR.glob("*.schema.json"):
        payload = cast(dict[str, object], json.loads(path.read_text(encoding="utf-8")))
        schemas.append((cast(str, payload["$id"]), Resource.from_contents(payload)))
        if path.name == "agent-skill-project-manager.schema.json":
            project_manager_schema = payload
    assert project_manager_schema is not None
    return Draft202012Validator(
        project_manager_schema,
        registry=Registry().with_resources(schemas),
        format_checker=FormatChecker(),
    )


def _errors(payload: WirePayload) -> list[str]:
    return sorted(error.message for error in _validator().iter_errors(payload))


def test_prepare_request_result_and_product_authorization_match_schema(
    tmp_path: Path,
) -> None:
    project = tmp_path / "target"
    project.mkdir()
    skill = service(tmp_path)
    request = PrepareProjectRequest(project_root=str(project.resolve()))
    result = skill.prepare_project(request)
    assert result.preparation is not None
    stage_request = StageAdvanceRequest(
        target=ProjectStage.PRODUCT_DISCOVERY,
        preparation=result.preparation,
    )
    authorization = skill.advance_stage(stage_request)

    for payload in (
        request.to_wire(),
        result.to_wire(),
        stage_request.to_wire(),
        authorization.to_wire(),
    ):
        assert _errors(payload) == []


def test_complete_dispatch_request_matches_schema(tmp_path: Path) -> None:
    preparation, request, spec, approval, design, plan = stage_chain(tmp_path)
    payload = StageAdvanceRequest(
        target=ProjectStage.DELIVERY_DISPATCH,
        preparation=preparation,
        project_request=request,
        product_spec=spec,
        product_approval=approval,
        technical_design=design,
        execution_plan=plan,
    ).to_wire()

    assert _errors(payload) == []


def test_skill_schema_rejects_extra_authority_and_wrong_digest_cardinality(
    tmp_path: Path,
) -> None:
    project = tmp_path / "target"
    project.mkdir()
    request = PrepareProjectRequest(project_root=str(project.resolve())).to_wire()
    request["organization_root"] = "/ambient-authority"
    assert _errors(request)

    control_path = PrepareProjectRequest(project_root=str(project.resolve())).to_wire()
    control_path["project_root"] = "/tmp/project\nforged"
    assert _errors(control_path)

    invalid_authorization: WirePayload = {
        "kind": "stage_advance_authorization",
        "schema_version": "v0.1",
        "target": "PRODUCT_DISCOVERY",
        "project_id": "project_delivery_001",
        "input_sha256s": ["a" * 64, "b" * 64],
        "authorized_at": NOW.isoformat(),
        "authorization_sha256": "c" * 64,
    }
    assert _errors(invalid_authorization)
