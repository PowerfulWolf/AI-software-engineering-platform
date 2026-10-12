"""Current facts and exact detail locators are separate from complete reading bodies."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from shutil import copyfile

import pytest
from jsonschema import Draft202012Validator, FormatChecker
from pydantic import TypeAdapter, ValidationError

from ai_software_engineer.team_view.models import RequestView, ScopeView, TaskView
from ai_software_engineer.team_view.read_models import (
    ProductSpecSource,
    RequestDetail,
    RequestSummary,
    TaskDetail,
    TaskSummary,
    TeamDetail,
    TeamDetailQuery,
    TeamDetailSource,
    TeamSummary,
)


def source(*, task: bool = False) -> TeamDetailSource:
    return TeamDetailSource(
        team_id="team_reads",
        project_id="project_reads",
        request_id="delivery_multi_reads",
        resource_kind="task" if task else "request",
        resource_id="delivery_reads" if task else "delivery_multi_reads",
        requirement_checkpoint_sha256="a" * 64,
        resource_checkpoint_sha256=("b" if task else "a") * 64,
        resource_state_sha256="d" * 64,
        work_kind="delivery" if task else None,
        task_id="task_reads" if task else None,
        task_revision=3 if task else None,
        task_intent_sha256="c" * 64 if task else None,
    )


def test_summary_explicit_fields_preserve_all_existing_current_fields() -> None:
    assert set(RequestSummary.model_fields) == (
        set(RequestView.model_fields) - {"dialogue", "documents"}
    ) | {"detail_source", "product_spec_source"}
    assert set(TaskSummary.model_fields) == (
        set(TaskView.model_fields) - {"documents", "timeline", "execution_history", "runs"}
    ) | {"detail_source"}


@pytest.mark.parametrize("field", ["task_id", "task_revision", "task_intent_sha256"])
def test_detail_source_rejects_partial_sql_task_identity(field: str) -> None:
    payload = source(task=True).to_wire()
    payload[field] = None
    with pytest.raises(ValidationError):
        TeamDetailSource.model_validate(payload)


@pytest.mark.parametrize(
    ("field", "value"),
    [("task_revision", True), ("task_revision", -1), ("resource_checkpoint_sha256", "")],
)
def test_detail_source_rejects_invalid_scalar_identity(field: str, value: object) -> None:
    with pytest.raises(ValidationError):
        TeamDetailSource.model_validate({**source(task=True).to_wire(), field: value})


def test_predispatch_and_verification_have_honest_distinct_locators() -> None:
    task = source(task=True)
    pred = TeamDetailSource.model_validate(
        {**task.to_wire(), "task_id": None, "task_revision": None, "task_intent_sha256": None}
    )
    assert pred.task_revision is None
    verification = TeamDetailSource.model_validate(
        {
            **pred.to_wire(),
            "work_kind": "candidate_verification",
            "resource_id": "verification_" + "d" * 32,
            "task_id": "task_verifier_reads",
            "source_task_id": "task_reads",
            "verification_plan_sha256": "d" * 64,
        }
    )
    assert verification.task_revision is None
    with pytest.raises(ValidationError):
        TeamDetailSource.model_validate({**verification.to_wire(), "task_revision": 1})
    with pytest.raises(ValidationError):
        TeamDetailSource.model_validate(
            {**verification.to_wire(), "task_id": verification.source_task_id}
        )


def test_request_cannot_carry_task_facts_or_a_different_resource_checkpoint() -> None:
    for change in ({"task_id": "task_reads"}, {"resource_checkpoint_sha256": "f" * 64}):
        with pytest.raises(ValidationError):
            TeamDetailSource.model_validate({**source().to_wire(), **change})


def test_query_round_trip_is_exact_and_detail_union_rejects_foreign_resource() -> None:
    locator = source()
    query = TeamDetailQuery.from_source(locator)
    assert query.source() == locator
    view = RequestView(
        id=locator.resource_id,
        project_id=locator.project_id,
        title="Current request",
        stage="DISCUSSING",
        scopes=(ScopeView(root="/workspace/source", selected_paths=(".",)),),
        next_action="继续讨论",
        checkpoint_sha256=locator.requirement_checkpoint_sha256,
    )
    detail = RequestDetail(as_of=datetime.now(UTC), scope=locator, resource=view)
    assert detail.kind == "request"
    with pytest.raises(ValidationError):
        RequestDetail(
            as_of=detail.as_of,
            scope=locator,
            resource=view.model_copy(update={"project_id": "project_other"}),
        )
    task = TaskView(
        id="delivery_reads",
        project_id=locator.project_id,
        request_id=locator.request_id,
        task_id="task_reads",
        task_revision=3,
        task_intent_sha256="c" * 64,
        title="Task",
        scope=view.scopes[0],
        status="IMPLEMENTING",
        checkpoint_stage="DELIVERING",
        terminal=False,
        last_activity=detail.as_of,
        next_action="等待当前执行",
    )
    with pytest.raises(ValidationError):
        TaskDetail(as_of=detail.as_of, scope=locator, resource=task)
    TaskDetail(as_of=detail.as_of, scope=source(task=True), resource=task)
    for change in ({"id": "delivery_foreign"}, {"project_id": "project_other"}):
        with pytest.raises(ValidationError):
            RequestSummary.model_validate(
                {
                    **view.model_dump(exclude={"dialogue", "documents"}),
                    "detail_source": locator,
                    **change,
                }
            )


@pytest.mark.parametrize("name", ["team-summary", "team-detail", "team-detail-query"])
def test_published_read_schemas_match_complete_models(name: str) -> None:
    schema = json.loads((Path(__file__).parents[2] / "schemas" / f"{name}.schema.json").read_text())
    assert schema.pop("$id") == f"https://ai-software-engineer.local/schemas/{name}.schema.json"
    assert schema.pop("$schema") == "https://json-schema.org/draft/2020-12/schema"
    expected = {
        "team-summary": TeamSummary.model_json_schema(),
        "team-detail": TypeAdapter(TeamDetail).json_schema(),
        "team-detail-query": TeamDetailQuery.model_json_schema(),
    }
    assert schema == expected[name]


@pytest.mark.parametrize("query", [False, True])
def test_static_schema_and_typed_model_agree_on_source_variant_rejections(query: bool) -> None:
    model = TeamDetailQuery if query else TeamDetailSource
    original = TeamDetailQuery.from_source(source(task=True)) if query else source(task=True)
    schema = model.model_json_schema()
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    validator.validate(original.to_wire())
    prefix = "expected_" if query else ""
    invalid = (
        {prefix + "task_id": None},
        {prefix + "task_revision": True},
        {prefix + "task_revision": -1},
        {"id" if query else "resource_id": "verification_" + "d" * 32},
        {prefix + "work_kind": "candidate_verification"},
        {"unknown_authority": True},
    )
    for change in invalid:
        payload = {**original.to_wire(), **change}
        assert list(validator.iter_errors(payload))
        with pytest.raises(ValidationError):
            model.model_validate(payload)


def test_product_metadata_preserves_real_joint_version_or_native_id() -> None:
    for payload in (
        {
            "spec_id": "product_spec_reads",
            "version": None,
            "sha256": "a" * 64,
            "source_uri": "ProductSpec://product_spec_reads",
        },
        {
            "spec_id": None,
            "version": 1,
            "sha256": "a" * 64,
            "source_uri": "request://delivery_multi_reads/ProductSpec",
        },
    ):
        spec = ProductSpecSource.model_validate(payload)
        Draft202012Validator(ProductSpecSource.model_json_schema()).validate(spec.to_wire())
        for change in (
            {"spec_id": None, "version": None},
            {"spec_id": "product_spec_reads", "version": 1},
            {"spec_id": None, "version": 0},
            {
                "source_uri": "request://delivery_multi_reads/ProductSpec"
                if spec.spec_id is not None
                else "ProductSpec://None"
            },
        ):
            invalid = {**payload, **change}
            assert list(
                Draft202012Validator(ProductSpecSource.model_json_schema()).iter_errors(invalid)
            )
            with pytest.raises(ValidationError):
                ProductSpecSource.model_validate(invalid)


def test_independent_read_schema_generation_is_repeatable_and_preserves_guards(
    tmp_path: Path,
) -> None:
    root = Path(__file__).parents[2]
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    (tmp_path / "schemas").mkdir()
    script = scripts / "sync-team-read-schemas.py"
    copyfile(root / "scripts" / script.name, script)
    environment = {**os.environ, "PYTHONPATH": str(root / "src")}
    subprocess.run((sys.executable, str(script)), check=True, env=environment, timeout=15)
    first = {path.name: path.read_bytes() for path in (tmp_path / "schemas").iterdir()}
    subprocess.run((sys.executable, str(script)), check=True, env=environment, timeout=15)
    assert {path.name: path.read_bytes() for path in (tmp_path / "schemas").iterdir()} == first
    assert set(first) == {
        "team-summary.schema.json",
        "team-detail.schema.json",
        "team-detail-query.schema.json",
    }
    for name, content in first.items():
        assert content == (root / "schemas" / name).read_bytes()
