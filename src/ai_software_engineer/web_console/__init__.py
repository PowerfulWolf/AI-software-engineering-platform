"""Browser-only Project Manager console."""

from .core import ConsoleCommandRejected, ProjectConsole, ProjectManagerConsolePort
from .models import (
    CONSOLE_INTENT_ADAPTER,
    ConsoleAction,
    ConsoleApprovalRequest,
    ConsoleCommandResult,
    ConsoleIntent,
    ConsoleOperation,
    ConsoleOperationStatus,
    ContinueDeliveryIntent,
    CreateRequirementProjectIntent,
    ProductApprovalIntent,
    ProductReplyIntent,
)
from .project_manager import OrganizationTeamConsoleHost, ProjectManagerConsoleAdapter
from .store import (
    ConsoleOperationConflict,
    ConsoleOperationError,
    ConsoleOperationNotFound,
    ConsoleOperationStore,
    FileConsoleOperationStore,
    InMemoryConsoleOperationStore,
)
from .transport import ConsoleApplication, SubmitOperation, TeamReader, create_console_app

__all__ = [
    "CONSOLE_INTENT_ADAPTER",
    "ConsoleAction",
    "ConsoleApplication",
    "ConsoleApprovalRequest",
    "ConsoleCommandRejected",
    "ConsoleCommandResult",
    "ConsoleIntent",
    "ConsoleOperation",
    "ConsoleOperationConflict",
    "ConsoleOperationError",
    "ConsoleOperationNotFound",
    "ConsoleOperationStatus",
    "ConsoleOperationStore",
    "ContinueDeliveryIntent",
    "CreateRequirementProjectIntent",
    "FileConsoleOperationStore",
    "InMemoryConsoleOperationStore",
    "OrganizationTeamConsoleHost",
    "ProductApprovalIntent",
    "ProductReplyIntent",
    "ProjectConsole",
    "ProjectManagerConsoleAdapter",
    "ProjectManagerConsolePort",
    "SubmitOperation",
    "TeamReader",
    "create_console_app",
]
