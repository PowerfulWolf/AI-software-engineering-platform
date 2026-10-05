"""Delivery responsibility and waiting cannot be chosen by model prose."""

import pytest

from ai_software_engineer.domain.delivery_disposition import (
    DeliveryFailureFacts,
    DeliveryNextAction,
    DeliveryResponsibility,
    decide_delivery_disposition,
)


def facts(
    classification: str, *, authorized: bool = False, budget: bool = True
) -> DeliveryFailureFacts:
    return DeliveryFailureFacts.model_validate(
        {
            "task_id": "task_disposition",
            "work_item_id": "work_disposition",
            "role": "coder",
            "classification": classification,
            "source_revision": "a" * 40,
            "task_intent_sha256": "b" * 64,
            "checkpoint_sequence": 2,
            "budget_available": budget,
            "retry_authorized": authorized,
        }
    )


@pytest.mark.parametrize(
    "classification",
    [
        "EXECUTION_UNCERTAIN",
        "PLATFORM_BUG",
        "INVALID_OUTPUT",
        "VERIFICATION_INCONCLUSIVE",
        "ENVIRONMENT_UNAVAILABLE",
        "SOURCE_PREPARATION_DRIFT",
        "ENGINEERING_AUTHORIZATION",
    ],
)
def test_recoverable_engineering_causes_do_not_request_product_or_terminate(
    classification: str,
) -> None:
    decision = decide_delivery_disposition(facts(classification))
    assert decision.responsibility is DeliveryResponsibility.ENGINEERING
    assert decision.action not in {
        DeliveryNextAction.TERMINATE,
        DeliveryNextAction.REQUEST_PRODUCT_DECISION,
        DeliveryNextAction.RETRY,
    }
    assert decision.resume_condition != "none"
    assert decision.source_facts_sha256 == decision.facts.facts_sha256


def test_only_explicit_business_ambiguity_requests_product_decision() -> None:
    decision = decide_delivery_disposition(facts("REQUIREMENT_AMBIGUITY"))
    assert decision.responsibility is DeliveryResponsibility.PRODUCT
    assert decision.action is DeliveryNextAction.REQUEST_PRODUCT_DECISION
    assert decision.resume_condition == "product_resolution"


@pytest.mark.parametrize("classification", ["TRANSIENT_INFRA", "QA_FINDING", "REVIEW_FINDING"])
def test_retry_and_feedback_require_both_frozen_authority_and_budget(classification: str) -> None:
    allowed = decide_delivery_disposition(facts(classification, authorized=True))
    assert allowed.responsibility is DeliveryResponsibility.TEAM
    assert allowed.resume_condition == "fresh_role_claim"
    refused = decide_delivery_disposition(facts(classification, authorized=False))
    assert refused.responsibility is DeliveryResponsibility.ENGINEERING
    assert refused.action is DeliveryNextAction.WAIT_DEPENDENCY
    exhausted = decide_delivery_disposition(facts(classification, authorized=True, budget=False))
    assert exhausted.action is DeliveryNextAction.TERMINATE
    assert exhausted.resume_condition == "none"


def test_true_policy_violation_cannot_be_cleaned_by_retry_authority() -> None:
    decision = decide_delivery_disposition(facts("POLICY_VIOLATION", authorized=True))
    assert decision.action is DeliveryNextAction.TERMINATE
    assert decision.resume_condition == "none"


def test_tampered_facts_or_model_fields_cannot_change_a_sealed_disposition() -> None:
    decision = decide_delivery_disposition(facts("EXECUTION_UNCERTAIN"))
    with pytest.raises(ValueError, match="exact facts"):
        type(decision).model_validate(
            {
                **decision.to_wire(),
                "facts": facts("REQUIREMENT_AMBIGUITY").to_wire(),
            }
        )
    with pytest.raises(ValueError):
        DeliveryFailureFacts.model_validate(
            {
                **decision.facts.to_wire(),
                "approved": True,
                "responsibility": "product",
            }
        )
    assert type(decision).model_validate(decision.to_wire()).disposition_sha256 == (
        decision.disposition_sha256
    )
