"""Candidate rescue bindings cannot become a generic source or budget override."""

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from ai_software_engineer.domain.execution_baseline import ExecutionBaselineBinding
from ai_software_engineer.manager.baseline_models import BaselineExecutionReservation


def _binding() -> dict[str, object]:
    return {
        "purpose": "rejected_candidate_rescue",
        "continuation_mode": "pause",
        "rejected_candidate_output_sha256": "1" * 64,
        "scope": {
            "team_id": "team_fixture",
            "project_id": "project_fixture",
            "repository_id": "repository_fixture",
            "repository_root": "/fixture/repository",
        },
        "task_id": "task_domain_001",
        "task_intent_sha256": "2" * 64,
        "sequence": 1,
        "approved_base_ref": "a" * 40,
        "branch_name": "ai/feature/recovery",
        "worktree_path": "/fixture/worktree",
        "prior_execution_base_ref": "a" * 40,
        "prior_source_revision": "a" * 40,
        "execution_base_ref": "a" * 40,
        "execution_source_revision": "b" * 40,
        "input_mode": "preserve_draft",
        "source_artifact_ids": ("art_plan_001",),
        "retained_patch": {"uri": "sidecar://complete-patch", "sha256": "3" * 64, "bytes": 1},
        "authority_source": "engineering_operator_decision",
        "authority_sha256": "4" * 64,
        "plan_sha256": "5" * 64,
        "facts_sha256": "6" * 64,
        "prior_task_revision": 11,
        "before_inventory_sha256": "7" * 64,
        "after_inventory_sha256": "7" * 64,
        "completed_at": datetime.now(UTC),
    }


def _reservation() -> dict[str, object]:
    return {
        "current_attempt": 10,
        "next_execution_attempt": 11,
        "retry_cause": "rejected_candidate_output",
        "rejected_candidate_output_sha256": "1" * 64,
        "original_run_id": "run_fixture_010",
        "current_invocation_start_sha256": "2" * 64,
        "current_invocation_outcome_sha256": "3" * 64,
    }


def test_binding_advances_only_execution_source_preserving_original_base() -> None:
    binding = ExecutionBaselineBinding.create(**_binding())
    binding.validate_integrity()
    assert (
        binding.execution_base_ref == binding.prior_execution_base_ref == binding.approved_base_ref
    )
    assert binding.execution_source_revision != binding.prior_source_revision


@pytest.mark.parametrize(
    "update",
    [
        {"continuation_mode": "resume"},
        {"authority_source": "organization_engineering_policy"},
        {"rejected_candidate_output_sha256": None},
        {"execution_base_ref": "c" * 40},
        {"execution_source_revision": "a" * 40},
        {"input_mode": "coder_reapply"},
        {"after_inventory_sha256": "8" * 64},
        {"completed_output_sha256": "8" * 64},
        {"service_pause_outcome_sha256": "8" * 64},
        {"superseded_implementation_artifact_id": "art_impl_001"},
    ],
)
def test_candidate_binding_rejects_mixed_or_expanding_authority(update: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        ExecutionBaselineBinding.create(**{**_binding(), **update})


def test_rejected_candidate_reservation_uses_exact_normal_work_successor() -> None:
    reservation = BaselineExecutionReservation.model_validate(_reservation())
    assert reservation.next_execution_attempt == reservation.current_attempt + 1
    assert reservation.retry_failure is None and not reservation.reservation_already_applied


@pytest.mark.parametrize(
    "update",
    [
        {"rejected_candidate_output_sha256": None},
        {"next_execution_attempt": 10},
        {"reservation_already_applied": True},
        {"original_run_id": None},
        {"current_invocation_outcome_sha256": None},
        {"interruption_receipt_sha256": "9" * 64},
        {"completed_output_sha256": "9" * 64},
        {"retry_cause": "uninvoked"},
    ],
)
def test_candidate_reservation_rejects_refund_or_other_proof(update: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        BaselineExecutionReservation.model_validate({**_reservation(), **update})
