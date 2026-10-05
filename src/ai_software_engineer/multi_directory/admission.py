"""Publication-only validation; sealed historical documents remain readable."""

from ai_software_engineer.domain.model import DomainModel, NonEmptyStr
from ai_software_engineer.manager.production_agents import (
    AcceptanceVerificationRejected,
    native_acceptance_mapping,
)
from ai_software_engineer.multi_directory.models import JointTechnicalDesign


def _retained_level(level: str) -> str:
    """Compare known historical inspection spelling only; never grant execution."""
    normalized = level.casefold()
    return {
        "source_inspection": "source-inspection",
        "document_inspection": "documentation",
        "document-inspection": "documentation",
    }.get(normalized, normalized)


class JointDesignVerificationRejected(ValueError):
    def __init__(self, failures: tuple[AcceptanceVerificationRejected, ...]) -> None:
        self.failures = failures
        super().__init__("; ".join(str(failure) for failure in failures))


class VerificationCorrectionRequirement(DomainModel):
    unit_id: NonEmptyStr
    acceptance_criterion_id: NonEmptyStr
    required_test_levels: tuple[NonEmptyStr, ...]


def verification_correction_requirements(
    feedback: tuple[JointTechnicalDesign, ...],
) -> tuple[VerificationCorrectionRequirement, ...]:
    retained: dict[tuple[str, str], set[str]] = {}
    for previous in feedback:
        for unit in previous.units:
            for mapping in unit.design.acceptance_mappings:
                try:
                    native_acceptance_mapping(mapping)
                except AcceptanceVerificationRejected as error:
                    if error.code == "INSPECTION_LEVELS":
                        key = (unit.unit_id, mapping.acceptance_criterion_id)
                        retained.setdefault(key, set()).update(mapping.test_levels)
    return tuple(
        VerificationCorrectionRequirement(
            unit_id=unit_id,
            acceptance_criterion_id=criterion_id,
            required_test_levels=tuple(sorted(levels)),
        )
        for (unit_id, criterion_id), levels in sorted(retained.items())
    )


def require_native_verification_contract(
    design: JointTechnicalDesign,
    feedback: JointTechnicalDesign | None = None,
    earlier_feedback: tuple[JointTechnicalDesign, ...] = (),
) -> None:
    """Reject exactly the mappings native delivery rejects, before Planner runs."""
    failures: list[AcceptanceVerificationRejected] = []
    retained_levels = {
        (item.unit_id, item.acceptance_criterion_id): item.required_test_levels
        for item in verification_correction_requirements(
            (*earlier_feedback, *((feedback,) if feedback is not None else ()))
        )
    }
    observed: set[tuple[str, str]] = set()
    for unit in design.units:
        for mapping in unit.design.acceptance_mappings:
            observed.add((unit.unit_id, mapping.acceptance_criterion_id))
            try:
                native_acceptance_mapping(mapping)
            except AcceptanceVerificationRejected as error:
                failures.append(error)
                continue
            previous = retained_levels.get((unit.unit_id, mapping.acceptance_criterion_id))
            if previous is not None and not {_retained_level(level) for level in previous} <= {
                _retained_level(level) for level in mapping.test_levels
            }:
                failures.append(
                    AcceptanceVerificationRejected(
                        mapping.acceptance_criterion_id, "VERIFICATION_LEVELS_REDUCED"
                    )
                )
    for _, criterion_id in sorted(set(retained_levels) - observed):
        failures.append(
            AcceptanceVerificationRejected(criterion_id, "VERIFICATION_MAPPING_REMOVED")
        )
    if failures:
        raise JointDesignVerificationRejected(tuple(failures))
