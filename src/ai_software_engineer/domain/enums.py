"""Canonical enum definitions shared by every domain boundary."""

from enum import StrEnum


class TaskStatus(StrEnum):
    NEW = "NEW"
    PLANNING = "PLANNING"
    IMPLEMENTING = "IMPLEMENTING"
    QA = "QA"
    REVIEW = "REVIEW"
    DONE = "DONE"
    BLOCKED = "BLOCKED"
    FAILED = "FAILED"


class AgentRole(StrEnum):
    ORCHESTRATOR = "orchestrator"
    CODER = "coder"
    QA = "qa"
    REVIEWER = "reviewer"


class ArtifactKind(StrEnum):
    PLAN = "plan"
    IMPLEMENTATION_REPORT = "implementation-report"
    QA_REPORT = "qa-report"
    REVIEW_REPORT = "review-report"


class NetworkAccess(StrEnum):
    NONE = "none"
    MODEL_ENDPOINT_ONLY = "model_endpoint_only"
    ALLOWLIST = "allowlist"


class EvidenceType(StrEnum):
    TEST = "test"
    COMMAND = "command"
    DIFF = "diff"
    FILE = "file"
    LOG = "log"
    METRIC = "metric"


class FindingSeverity(StrEnum):
    INFO = "INFO"
    MINOR = "MINOR"
    MAJOR = "MAJOR"
    BLOCKER = "BLOCKER"


class ChangeType(StrEnum):
    ADDED = "added"
    MODIFIED = "modified"
    DELETED = "deleted"
    RENAMED = "renamed"


class ImplementationTestStatus(StrEnum):
    PASS = "PASS"
    FAIL = "FAIL"
    NOT_RUN = "NOT_RUN"


class QaReportStatus(StrEnum):
    PASS = "PASS"
    FAIL = "FAIL"


class QaCriterionStatus(StrEnum):
    PASS = "PASS"
    FAIL = "FAIL"
    NOT_TESTED = "NOT_TESTED"


class QaTestStatus(StrEnum):
    PASS = "PASS"
    FAIL = "FAIL"
    ERROR = "ERROR"


class ReviewVerdict(StrEnum):
    APPROVE = "APPROVE"
    REJECT = "REJECT"


class ReviewDimension(StrEnum):
    CORRECTNESS = "correctness"
    ACCEPTANCE = "acceptance"
    REGRESSION = "regression"
    SECURITY = "security"
    MAINTAINABILITY = "maintainability"
    PERFORMANCE = "performance"
    CONTRACT_CONSISTENCY = "契约一致性"
