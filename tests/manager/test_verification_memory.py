"""Rejected native mappings must release completed readers and their full histories."""

import gc
import weakref
from pathlib import Path

import pytest

from ai_software_engineer.manager.production_agents import (
    AcceptanceVerificationRejected,
    native_acceptance_mapping,
)
from ai_software_engineer.multi_directory.admission import (
    JointDesignVerificationRejected,
    require_native_verification_contract,
)
from tests.manager.test_joint_contracts import checkpoint
from tests.manager.test_joint_verification_admission import inspected_design


class _ReadScopeLifetime:
    """Represents the larger snapshot/history owned by a validation caller."""


@pytest.mark.parametrize("boundary", ["native", "joint"])
def test_rejected_mapping_does_not_retain_completed_read_scope(
    tmp_path: Path, boundary: str
) -> None:
    cp = checkpoint(tmp_path)
    assert cp.design is not None
    invalid = inspected_design(cp.design, "source", ("source_inspection", "integration"))

    def read_scope() -> weakref.ReferenceType[_ReadScopeLifetime]:
        lifetime = _ReadScopeLifetime()
        reference = weakref.ref(lifetime)
        try:
            if boundary == "native":
                native_acceptance_mapping(invalid.units[0].design.acceptance_mappings[0])
            else:
                require_native_verification_contract(invalid)
        except (AcceptanceVerificationRejected, JointDesignVerificationRejected) as failure:
            assert "ac_001_001" in str(failure)
            assert "检查不能替代" in str(failure)
        else:
            pytest.fail("invalid inspection mapping was accepted")
        return reference

    references = [read_scope() for _ in range(3)]
    gc.collect()
    assert all(reference() is None for reference in references), (
        "discarded validation errors retained completed read frames and their snapshot/history"
    )
