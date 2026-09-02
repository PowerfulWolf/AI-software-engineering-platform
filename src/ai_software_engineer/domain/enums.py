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


class ProjectRequestStatus(StrEnum):
    PRODUCT_DISCOVERY = "PRODUCT_DISCOVERY"
    WAITING_PRODUCT_APPROVAL = "WAITING_PRODUCT_APPROVAL"
    DESIGNING = "DESIGNING"
    PLANNING = "PLANNING"
    READY_FOR_DELIVERY = "READY_FOR_DELIVERY"
    DELIVERING = "DELIVERING"
    REPORTING = "REPORTING"
    DONE = "DONE"
    WAITING_HUMAN = "WAITING_HUMAN"
    BLOCKED = "BLOCKED"


class ProductSpecStatus(StrEnum):
    DRAFT = "DRAFT"
    READY_FOR_REVIEW = "READY_FOR_REVIEW"


class ProductApprovalDecision(StrEnum):
    APPROVED = "APPROVED"
    REQUEST_CHANGES = "REQUEST_CHANGES"


class RequirementPriority(StrEnum):
    MUST = "MUST"
    SHOULD = "SHOULD"
    COULD = "COULD"


class AgentRole(StrEnum):
    """Delivery-runtime roles bound to Task artifacts and state transitions."""

    ORCHESTRATOR = "orchestrator"
    CODER = "coder"
    QA = "qa"
    REVIEWER = "reviewer"


class OrganizationRole(StrEnum):
    """Long-lived roles that an organization-owned AgentProfile may declare."""

    PROJECT_MANAGER = "project_manager"
    PRODUCT = "product"
    DESIGNER = "designer"
    PLANNER = "planner"
    ORCHESTRATOR = "orchestrator"
    CODER = "coder"
    QA = "qa"
    REVIEWER = "reviewer"


class BrainTier(StrEnum):
    ECONOMY = "economy"
    STANDARD = "standard"
    REASONING = "reasoning"
    CRITICAL = "critical"


class RiskTier(StrEnum):
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    CRITICAL = "critical"


class WorkItemStatus(StrEnum):
    READY = "READY"
    LEASED = "LEASED"
    RUNNING = "RUNNING"
    WAITING_HUMAN = "WAITING_HUMAN"
    WAITING_DEPENDENCY = "WAITING_DEPENDENCY"
    RETRY_SCHEDULED = "RETRY_SCHEDULED"
    CLOSED = "CLOSED"


class ModelRouteReason(StrEnum):
    DEFAULT = "default"
    TASK_COMPLEXITY = "task_complexity"
    RISK_FLOOR = "risk_floor"
    ROLE_FLOOR = "role_floor"
    CONTEXT_CAPACITY = "context_capacity"
    OBJECTIVE_ESCALATION = "objective_escalation"
    BUDGET_CONSTRAINT = "budget_constraint"
    OPERATOR_OVERRIDE = "operator_override"


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
