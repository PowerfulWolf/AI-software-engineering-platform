"""Read-only instructions for the trusted local service-maintenance entry."""

import shlex
from pathlib import Path
from typing import Literal

from ai_software_engineer.domain.model import DomainModel, NonEmptyStr


class MaintenanceCompletionGuide(DomainModel):
    schema_version: Literal["v1"] = "v1"
    prepare_command: NonEmptyStr
    complete_command: NonEmptyStr


def completion_guide(config_path: Path, state_root: Path) -> MaintenanceCompletionGuide:
    script = Path(__file__).resolve().parents[3] / "scripts" / "ase-console-service.sh"
    prefix = (
        f"ASE_CONFIG={shlex.quote(str(config_path))} "
        f"ASE_SERVICE_STATE_DIR={shlex.quote(str(state_root))} "
        f"{shlex.quote(str(script))}"
    )
    return MaintenanceCompletionGuide(
        prepare_command=f"{prefix} prepare-maintenance-completion",
        complete_command=f"{prefix} complete-maintenance PLAN_SHA256 --confirm-restore-normal",
    )
