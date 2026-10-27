"""Executable red gates for the deliberately inactive static-QA recovery route.

Removing the xfail markers is appropriate only after the public wait transaction,
current-fact proof and dedicated output validation are implemented together.
"""

from __future__ import annotations

import pytest

from ai_software_engineer.agents import verification_output
from ai_software_engineer.domain.delivery_resolution import DeliveryResolutionKind


@pytest.mark.xfail(strict=True, reason="public owner-fenced static QA wait resolution is absent")
def test_public_wait_resolution_admits_exact_missing_entry_qa() -> None:
    assert "STATIC_QA_MISSING_ENTRY" in {kind.value for kind in DeliveryResolutionKind}


def test_commandless_static_qa_has_a_dedicated_trusted_contract() -> None:
    assert hasattr(verification_output, "TrustedStaticQaMissingEntryOutputContract")
