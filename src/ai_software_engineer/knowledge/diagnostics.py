"""Fixed diagnostic labels: never expose document/provider exception payloads."""

from ai_software_engineer.knowledge.models import KnowledgeError

_SAFE_CODES = frozenset(
    {
        "LEGACY_KNOWLEDGE_SCOPE_CHANGED",
        "FROZEN_SOURCE_CONFLICT",
        "UNRESOLVED_SOURCE",
        "BASELINE_REPOSITORY",
        "CONTEXT_TEAM",
        "SOURCE_OWNER",
        "SOURCE_REPOSITORY",
        "RECORD_CONFLICT",
        "RECORD_NOT_FOUND",
        "STORE_PATH",
        "STORE_ROOT_CHANGED",
        "STORE_CORRUPT",
        "STORE_LIMIT",
        "RESOLUTION_LINEAGE",
        "RESOLUTION_INTEGRITY",
        "RESOLUTION_REQUIRES_REDACTION",
        "RESOLUTION_EVALUATION_CONFLICT",
        "RESUME_INTEGRITY",
        "RESUME_REQUIRES_NEW_RUN_CONTEXT",
        "RESOLUTION_REQUIRES_NEW_RUN",
        "CONSULTATION_CONFLICT",
        "CONSULTATION_INTEGRITY",
        "WORKFLOW_CONSULTATION_MISSING",
        "WORKFLOW_CONSULTATION_INVALID",
        "WORKFLOW_CONTEXT_MISMATCH",
    }
)


def knowledge_error_code(error: KnowledgeError) -> str:
    message = str(error)
    return message if message in _SAFE_CODES else "KNOWLEDGE_UNCLASSIFIED"
