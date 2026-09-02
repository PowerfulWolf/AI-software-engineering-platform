"""Designer context lineage, policy, and identity tests."""

from datetime import datetime, timedelta
from pathlib import Path
from typing import cast

import pytest
from pydantic import ValidationError

from ai_software_engineer.design import (
    DESIGNER_AGENT_PERMISSIONS,
    DesignContextBuilder,
    DesignContextIntegrityError,
    DesignContextLineageError,
    DesignContextManifest,
)
from ai_software_engineer.domain.model import JsonValue
from tests.design.factories import NOW, approved_facts


def test_context_carries_full_task_free_facts_and_fail_closed_policy(tmp_path: Path) -> None:
    command, _, _ = approved_facts(tmp_path)
    builder = DesignContextBuilder()
    context = builder.build(
        command.preparation,
        command.project_profile,
        command.project_baseline,
        command.request_revision.request,
        command.product_spec,
        command.product_approval,
        command.solution_design_authorization,
        built_at=NOW,
    )
    replay = builder.build(
        context.preparation,
        context.project_profile,
        context.project_baseline,
        context.project_request,
        context.product_spec,
        context.product_approval,
        context.solution_design_authorization,
        built_at=NOW + timedelta(hours=1),
    )

    assert replay.context_id == context.context_id
    assert replay.context_sha256 == context.context_sha256
    assert replay.built_at != context.built_at
    assert context.permissions == DESIGNER_AGENT_PERMISSIONS
    assert context.permissions.write_code is False
    assert context.permissions.execute_shell is False
    assert context.permissions.modify_product_spec is False
    assert context.permissions.advance_project_stage is False
    assert not hasattr(context, "task_id")
    assert len(context.sources) == 8
    assert context.project_profile.languages
    assert context.project_baseline.rules
    context.validate_integrity()


def test_context_rejects_stale_request_broken_authorization_and_tamper(tmp_path: Path) -> None:
    command, _, _ = approved_facts(tmp_path)
    builder = DesignContextBuilder()
    stale_request = command.request_revision.request.model_copy(update={"request_sha256": "f" * 64})
    with pytest.raises(DesignContextLineageError):
        builder.build(
            command.preparation,
            command.project_profile,
            command.project_baseline,
            stale_request,
            command.product_spec,
            command.product_approval,
            command.solution_design_authorization,
            built_at=NOW,
        )

    with pytest.raises(DesignContextLineageError):
        builder.build(
            command.preparation,
            command.project_profile,
            command.project_baseline,
            command.request_revision.request,
            command.product_spec,
            command.product_approval,
            command.solution_design_authorization.model_copy(
                update={"authorization_sha256": "e" * 64}
            ),
            built_at=NOW,
        )

    context = builder.build(
        command.preparation,
        command.project_profile,
        command.project_baseline,
        command.request_revision.request,
        command.product_spec,
        command.product_approval,
        command.solution_design_authorization,
        built_at=NOW,
    )
    with pytest.raises(DesignContextIntegrityError):
        context.model_copy(update={"context_sha256": "d" * 64}).validate_integrity()


def test_context_rejects_naive_time_and_permission_widening(tmp_path: Path) -> None:
    command, _, _ = approved_facts(tmp_path)
    with pytest.raises(DesignContextLineageError, match="timezone-aware"):
        DesignContextBuilder().build(
            command.preparation,
            command.project_profile,
            command.project_baseline,
            command.request_revision.request,
            command.product_spec,
            command.product_approval,
            command.solution_design_authorization,
            built_at=datetime(2026, 9, 2, 12, 0),
        )

    context = DesignContextBuilder().build(
        command.preparation,
        command.project_profile,
        command.project_baseline,
        command.request_revision.request,
        command.product_spec,
        command.product_approval,
        command.solution_design_authorization,
        built_at=NOW,
    )
    wire = context.to_wire()
    permissions = cast(dict[str, JsonValue], wire["permissions"])
    permissions["execute_shell"] = True
    with pytest.raises(ValidationError):
        DesignContextManifest.model_validate(wire)
