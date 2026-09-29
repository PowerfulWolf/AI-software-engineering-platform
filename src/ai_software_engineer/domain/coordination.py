"""Manager advice is a scoped proposal, never dispatch or approval authority."""

from typing import Annotated, Literal

from pydantic import Field

from ai_software_engineer.domain.artifact import Sha256
from ai_software_engineer.domain.model import DomainModel, NonEmptyStr

CoordinationAction = Literal["RETRY_STAGE", "PROPOSE_RECOVERY", "WAITING_HUMAN"]
CoordinationText = Annotated[str, Field(min_length=1, max_length=2000)]


class ManagerCoordinationDraft(DomainModel):
    action: CoordinationAction
    summary: CoordinationText
    next_action: CoordinationText
    responsible_actor: CoordinationText
    resume_condition: CoordinationText


class ManagerCoordinationAdvice(DomainModel):
    kind: Literal["manager_stage_advice"] = "manager_stage_advice"
    requirement_id: NonEmptyStr
    stage: NonEmptyStr
    source_facts_sha256: Sha256
    source_checkpoint_sha256: Sha256
    input_sha256: Sha256
    manager_run_id: NonEmptyStr
    provider: NonEmptyStr
    model: NonEmptyStr
    draft: ManagerCoordinationDraft
