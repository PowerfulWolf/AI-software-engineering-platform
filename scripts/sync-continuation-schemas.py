"""Add frozen continuation contracts without erasing handwritten Schema conditions."""

import json
from pathlib import Path
from typing import Annotated, cast

from pydantic import Field, TypeAdapter

from ai_software_engineer.agents.models import AgentErrorCode, AgentResult
from ai_software_engineer.domain.continuation import InterruptionContinuationPolicy
from ai_software_engineer.domain.retry_policy import TRANSIENT_CODES
from ai_software_engineer.domain.task import Task
from ai_software_engineer.orchestration.continuation_models import (
    ContinuationAdmission,
    ExecutionCaptureStart,
    ExecutionCaptureStop,
    ExecutionInterruptionReceipt,
)

SCHEMAS = Path(__file__).resolve().parents[1] / "schemas"


def _object(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        raise TypeError("Schema nodes must be objects")
    return cast(dict[str, object], value)


def _write(filename: str, schema: dict[str, object]) -> None:
    schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
    schema["$id"] = f"https://ai-software-engineer.local/schemas/{filename}"
    (SCHEMAS / filename).write_text(json.dumps(schema, ensure_ascii=False, indent=2) + "\n")


def _result_schema() -> dict[str, object]:
    schema = AgentResult.model_json_schema()
    failure = schema["$defs"]["AgentFailure"]
    failure["allOf"] = [
        {
            "if": {"required": ["code"], "properties": {"code": {"const": "WORK_INTERRUPTED"}}},
            "then": {"properties": {"transient": {"const": False}}},
        }
    ]
    schema["allOf"] = [
        {
            "if": {"properties": {"status": {"const": "SUCCEEDED"}}},
            "then": {
                "required": ["artifact"],
                "properties": {"artifact": {"type": "object"}, "error": {"type": "null"}},
            },
            "else": {
                "required": ["error"],
                "properties": {"error": {"type": "object"}, "artifact": {"type": "null"}},
            },
        },
        {
            "if": {"properties": {"status": {"const": "TIMED_OUT"}}},
            "then": {"properties": {"error": {"properties": {"code": {"const": "TIMEOUT"}}}}},
        },
        {
            "if": {
                "required": ["error"],
                "properties": {
                    "error": {
                        "type": "object",
                        "required": ["code"],
                        "properties": {"code": {"const": "TIMEOUT"}},
                    }
                },
            },
            "then": {"properties": {"status": {"const": "TIMED_OUT"}}},
        },
        {
            "if": {
                "required": ["error"],
                "properties": {
                    "error": {
                        "type": "object",
                        "required": ["code"],
                        "properties": {"code": {"const": "WORK_INTERRUPTED"}},
                    }
                },
            },
            "then": {"properties": {"status": {"const": "FAILED"}}},
        },
    ]
    return schema


def main() -> None:
    expected = Task.model_json_schema()
    field = "interruption_continuation_policy"
    for path in sorted(SCHEMAS.glob("*.schema.json")):
        schema = _object(json.loads(path.read_text()))
        before = json.dumps(schema)
        definitions = _object(schema.get("$defs", {}))
        task = definitions.get("Task", schema if path.name == "task.schema.json" else None)
        if task is not None:
            _object(_object(task)["properties"])[field] = expected["properties"][field]
            definitions["InterruptionContinuationPolicy"] = expected["$defs"][
                "InterruptionContinuationPolicy"
            ]
            schema["$defs"] = definitions
        error_code = definitions.get("AgentErrorCode")
        if error_code is not None:
            _object(error_code)["enum"] = [code.value for code in AgentErrorCode]
        if json.dumps(schema) != before:
            path.write_text(json.dumps(schema, ensure_ascii=False, indent=2) + "\n")
    _write(
        "interruption-continuation-policy.schema.json",
        InterruptionContinuationPolicy.model_json_schema(),
    )
    _write("agent-result.schema.json", _result_schema())
    continuation_schema = TypeAdapter(
        Annotated[
            ExecutionInterruptionReceipt | ContinuationAdmission,
            Field(discriminator="kind"),
        ]
    ).json_schema()
    receipt_node = continuation_schema["$defs"]["ExecutionInterruptionReceipt"]
    receipt_node["properties"]["request"] = {
        "allOf": [
            receipt_node["properties"]["request"],
            {
                "properties": {
                    "role": {"const": "coder"},
                }
            },
        ]
    }
    receipt_node["properties"]["mutation_paths"]["uniqueItems"] = True
    receipt_node["allOf"] = [
        {
            "if": {"properties": {"schema_version": {"const": "v1"}}},
            "then": {
                "properties": {
                    "request": {
                        "properties": {
                            "attempt": {"const": 1},
                            "continuation_checkpoint_id": {"type": "null"},
                        }
                    },
                    "mutation_paths": {"minItems": 1},
                    "previous_admission_sha256": {"type": "null"},
                    "capture": {"$ref": "#/$defs/CapturedChanges"},
                    "process_stop": {"$ref": "#/$defs/NativeProcessStop"},
                }
            },
            "else": {"properties": {"capture": {"$ref": "#/$defs/CapturedMutations"}}},
        },
        {"properties": {"capture": {"properties": {"attempt": {"const": 1}}}}},
        {
            "if": {"properties": {"cause": {"const": "local_execution_limit"}}},
            "then": {
                "properties": {
                    "original_error_code": {"const": "TIMEOUT"},
                    "process_stop": {"properties": {"kind": {"const": "local_execution_limit"}}},
                }
            },
            "else": {"properties": {"original_error_code": {"enum": sorted(TRANSIENT_CODES)}}},
        },
        {
            "if": {
                "properties": {
                    "process_stop": {
                        "required": ["origin"],
                        "properties": {"origin": {"const": "synchronous_responses_tool_loop"}},
                    }
                }
            },
            "then": {
                "properties": {"schema_version": {"const": "v2"}},
                "allOf": [
                    {
                        "if": {"properties": {"cause": {"const": "provider_transient"}}},
                        "then": {
                            "properties": {
                                "process_stop": {
                                    "properties": {"kind": {"const": "failed"}},
                                }
                            }
                        },
                    }
                ],
            },
        },
    ]
    continuation_schema["$defs"]["SynchronousToolLoopStop"]["properties"][
        "completed_operation_ids"
    ]["uniqueItems"] = True
    admission_node = continuation_schema["$defs"]["ContinuationAdmission"]
    admission_node["properties"]["new_request"] = {
        "allOf": [
            admission_node["properties"]["new_request"],
            {
                "properties": {
                    "role": {"const": "coder"},
                }
            },
        ]
    }
    admission_node["allOf"] = [
        {
            "if": {"properties": {"schema_version": {"const": "v1"}}},
            "then": {
                "properties": {
                    "new_request": {
                        "properties": {
                            "attempt": {"const": 2},
                            "continuation_checkpoint_id": {"type": "null"},
                        }
                    },
                    "interrupted_attempt": {"type": "null"},
                }
            },
            "else": {
                "required": ["interrupted_attempt"],
                "properties": {
                    "interrupted_attempt": {"type": "integer", "minimum": 1, "maximum": 399},
                    "new_request": {"properties": {"attempt": {"minimum": 2}}},
                },
            },
        }
    ]
    _write("execution-continuation.schema.json", continuation_schema)
    capture_schema = TypeAdapter(
        Annotated[ExecutionCaptureStart | ExecutionCaptureStop, Field(discriminator="kind")]
    ).json_schema()
    capture_schema["$defs"]["ExecutionCaptureStart"]["properties"]["request"] = {
        "allOf": [
            {"$ref": "#/$defs/AgentRequest"},
            {"properties": {"role": {"const": "coder"}}},
        ]
    }
    capture_schema["$defs"]["ExecutionCaptureStop"]["allOf"] = [
        {
            "if": {
                "required": ["cause"],
                "properties": {
                    "cause": {"const": "local_execution_limit"},
                },
            },
            "then": {
                "required": ["original_error_code"],
                "properties": {
                    "original_error_code": {"const": "TIMEOUT"},
                    "process_stop": {"properties": {"kind": {"const": "local_execution_limit"}}},
                },
            },
        },
        {
            "if": {
                "required": ["cause"],
                "properties": {
                    "cause": {"const": "provider_transient"},
                },
            },
            "then": {
                "required": ["original_error_code"],
                "properties": {
                    "original_error_code": {"enum": sorted(TRANSIENT_CODES)},
                    "process_stop": {"properties": {"kind": {"const": "failed"}}},
                },
            },
        },
    ]
    _write("execution-capture.schema.json", capture_schema)


if __name__ == "__main__":
    main()
