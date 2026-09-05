"""Structured upstream producer contracts for Product, Designer, and Planner."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from ai_software_engineer.agents import StructuredModelResult
from ai_software_engineer.design import DesignerAgentRunStatus
from ai_software_engineer.planning import PlannerAgentRequest, PlannerAgentRunStatus
from ai_software_engineer.product import ProductAgentRunStatus
from ai_software_engineer.project_manager.production_agents import (
    StructuredDesignerAgentAdapter,
    StructuredPlannerAgentAdapter,
    StructuredProductAgentAdapter,
)
from tests.design.test_agents import _request as designer_request
from tests.planning.test_agent_contract import _context as planner_context
from tests.product.test_agents import _request as product_request


class _StructuredClient:
    def __init__(self, payload: Mapping[str, object]) -> None:
        self.payload = payload
        self.schemas: list[Mapping[str, object]] = []

    def complete(
        self,
        *,
        instructions: str,
        input_payload: Mapping[str, object],
        output_schema: Mapping[str, object],
        timeout_seconds: int,
    ) -> StructuredModelResult:
        assert instructions and input_payload and timeout_seconds > 0
        self.schemas.append(output_schema)
        return StructuredModelResult(payload=self.payload, duration_ms=7)


def test_product_draft_becomes_digest_bound_product_spec(tmp_path: Path) -> None:
    request = product_request(tmp_path)
    result = StructuredProductAgentAdapter(
        _StructuredClient(
            {
                "action": "ready",
                "summary": "Add deterministic greeting behavior.",
                "goals": ["Expose one deterministic greeting."],
                "requirements": [
                    {
                        "statement": "The greeting is stable for the same input.",
                        "priority": "MUST",
                        "rationale": "The user requested deterministic behavior.",
                        "acceptance": [
                            {
                                "description": "Repeated calls return the same greeting.",
                                "verification": "Run the project unit test.",
                                "test_ids": ["test_greeting_is_deterministic"],
                            }
                        ],
                    }
                ],
            }
        )
    ).run(request)

    assert result.status is ProductAgentRunStatus.SUCCEEDED
    assert result.product_spec is not None
    result.product_spec.validate_integrity()
    assert result.product_spec.request_id == request.request_id
    assert result.product_spec.requirements[0].acceptance_criterion_ids == ("ac_001_001",)


def test_designer_draft_must_cover_exact_approved_ids(tmp_path: Path) -> None:
    request, _ = designer_request(tmp_path)
    spec = request.context.product_spec
    requirement_id = spec.requirements[0].id
    acceptance_id = spec.acceptance_criteria[0].id
    result = StructuredDesignerAgentAdapter(
        _StructuredClient(
            {
                "summary": "Change the focused module and verify it independently.",
                "components": [
                    {
                        "key": "target",
                        "name": "Target module",
                        "responsibility": "Implement the approved behavior.",
                        "affected_paths": ["src/**", "tests/**"],
                    }
                ],
                "requirement_mappings": [
                    {
                        "requirement_id": requirement_id,
                        "component_keys": ["target"],
                        "approach": "Follow the discovered project conventions.",
                    }
                ],
                "acceptance_mappings": [
                    {
                        "acceptance_criterion_id": acceptance_id,
                        "verification_strategy": "Run focused unit tests.",
                        "test_levels": ["unit"],
                    }
                ],
                "implementation_steps": [
                    {
                        "key": "implement",
                        "description": "Implement the focused change.",
                        "component_keys": ["target"],
                        "verification": "Run focused unit tests.",
                    }
                ],
            }
        )
    ).run(request)

    assert result.status is DesignerAgentRunStatus.SUCCEEDED
    assert result.technical_design is not None
    result.technical_design.validate_integrity()
    assert result.technical_design.product_spec_sha256 == spec.product_spec_sha256


def test_planner_draft_remains_abstract_and_serial(tmp_path: Path) -> None:
    context = planner_context(tmp_path)
    request = PlannerAgentRequest(
        run_id="run_planner_production_001",
        project_id=context.project_id,
        request_id=context.request_id,
        context=context,
    )
    capabilities = {
        "coder": "implementation",
        "qa": "testing",
        "reviewer": "review",
    }
    phases = [
        {
            "role": role,
            "objective": f"Complete {role} work independently.",
            "required_capabilities": [capabilities[role]],
            "risk": "normal",
            "minimum_brain_tier": "standard",
            "checkpoints": [f"{role} artifact is verified"],
        }
        for role in ("coder", "qa", "reviewer")
    ]
    result = StructuredPlannerAgentAdapter(_StructuredClient({"phases": phases})).run(request)

    assert result.status is PlannerAgentRunStatus.SUCCEEDED
    assert result.execution_plan is not None
    result.execution_plan.validate_integrity()
    assert tuple(phase.role.value for phase in result.execution_plan.phases) == (
        "coder",
        "qa",
        "reviewer",
    )
