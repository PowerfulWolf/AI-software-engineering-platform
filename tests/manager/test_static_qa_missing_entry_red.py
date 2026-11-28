"""Executable red gates for the deliberately inactive static-QA recovery route.

Removing the xfail markers is appropriate only after the public wait transaction,
current-fact proof and dedicated output validation are implemented together.
"""

from __future__ import annotations

from ai_software_engineer.agents import verification_output


def test_commandless_static_qa_has_a_dedicated_trusted_contract() -> None:
    assert hasattr(verification_output, "TrustedStaticQaMissingEntryOutputContract")
