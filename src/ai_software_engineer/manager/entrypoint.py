"""Application-host binding for the CLI-facing Manager service."""

from collections.abc import Callable

from ai_software_engineer.manager.delivery import UnifiedProjectEntryService
from ai_software_engineer.multi_directory.service import JointDeliveryService


class ProjectEntryNotConfigured(RuntimeError):
    """The application host has not bound its organization team composition."""


ProjectEntryProvider = Callable[[], UnifiedProjectEntryService]
_provider: ProjectEntryProvider | None = None
_default_service: UnifiedProjectEntryService | None = None
_requirement_service: JointDeliveryService | None = None


def configure_project_entry(provider: ProjectEntryProvider) -> None:
    """Bind one host-owned team composition without exposing its paths to CLI users."""
    global _provider
    _provider = provider


def project_entry() -> UnifiedProjectEntryService:
    """Resolve the host-owned Manager application service."""
    if _provider is not None:
        return _provider()
    global _default_service
    if _default_service is None:
        from ai_software_engineer.manager.production_host import TeamHost

        _default_service = TeamHost.from_environment().project_entry()
    return _default_service


def requirement_entry() -> JointDeliveryService:
    global _requirement_service
    if _requirement_service is None:
        from ai_software_engineer.manager.production_host import TeamHost

        _requirement_service = TeamHost.from_environment().requirement_entry()
    return _requirement_service


__all__ = [
    "ProjectEntryNotConfigured",
    "ProjectEntryProvider",
    "configure_project_entry",
    "project_entry",
]
