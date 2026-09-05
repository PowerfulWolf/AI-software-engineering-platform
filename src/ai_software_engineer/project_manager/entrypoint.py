"""Application-host binding for the CLI-facing Project Manager service."""

from collections.abc import Callable

from ai_software_engineer.project_manager.delivery import UnifiedProjectEntryService


class ProjectEntryNotConfigured(RuntimeError):
    """The application host has not bound its organization team composition."""


ProjectEntryProvider = Callable[[], UnifiedProjectEntryService]
_provider: ProjectEntryProvider | None = None
_default_service: UnifiedProjectEntryService | None = None


def configure_project_entry(provider: ProjectEntryProvider) -> None:
    """Bind one host-owned team composition without exposing its paths to CLI users."""
    global _provider
    _provider = provider


def project_entry() -> UnifiedProjectEntryService:
    """Resolve the host-owned Project Manager application service."""
    if _provider is not None:
        return _provider()
    global _default_service
    if _default_service is None:
        from ai_software_engineer.project_manager.production_host import OrganizationTeamHost

        _default_service = OrganizationTeamHost.from_environment().project_entry()
    return _default_service


__all__ = [
    "ProjectEntryNotConfigured",
    "ProjectEntryProvider",
    "configure_project_entry",
    "project_entry",
]
