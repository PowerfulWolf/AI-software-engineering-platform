"""Provider admission regressions discovered during real self-delivery."""

import json

from jsonschema import Draft202012Validator

from ai_software_engineer.agents.codex_cli import (
    CodexInvocationResult,
    _artifact_schema,
    _classify_cli_failure,
)
from ai_software_engineer.agents.models import AgentErrorCode
from ai_software_engineer.domain.enums import AgentRole
from tests.domain.factories import make_coder_progress_artifact, make_implementation_artifact


def test_coder_union_is_nested_under_object_root() -> None:
    schema = _artifact_schema(AgentRole.CODER)
    assert schema["type"] == "object"
    assert "anyOf" not in schema
    validator = Draft202012Validator(schema)
    for artifact in (make_coder_progress_artifact(), make_implementation_artifact()):
        # Strict output requires defaulted and nullable fields too.
        payload = json.loads(artifact.model_dump_json())
        validator.validate({"artifact": payload})
    assert not validator.is_valid({"artifact": {}})
    assert not validator.is_valid({"artifact": payload, "extra": True})


def test_invalid_schema_does_not_become_rate_limit_from_prompt_hash() -> None:
    result = CodexInvocationResult(
        returncode=1,
        stderr='user\nsha=abc429def rate limit\nERROR: {"error": '
        '{"code": "invalid_json_schema"}, "status": 400}',
    )
    assert _classify_cli_failure(result) == (AgentErrorCode.INVALID_OUTPUT, False)


def test_hash_digits_are_not_http_rate_limit() -> None:
    result = CodexInvocationResult(returncode=1, stderr="ERROR: request abc429def failed")
    assert _classify_cli_failure(result)[0] == AgentErrorCode.PROVIDER_UNAVAILABLE
    result = CodexInvocationResult(returncode=1, stderr="ERROR: HTTP 429 Too Many Requests")
    assert _classify_cli_failure(result) == (AgentErrorCode.RATE_LIMITED, True)
