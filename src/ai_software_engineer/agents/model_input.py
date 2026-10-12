"""Trusted final-input preparation; never a model tool or execution admission."""

import hashlib
from typing import Protocol, runtime_checkable

from ai_software_engineer.agents.models import AgentRequest
from ai_software_engineer.agents.openai_compatible import ContextResolver
from ai_software_engineer.context.builder import estimate_input_tokens
from ai_software_engineer.context.ports import ContextBudgetExceeded
from ai_software_engineer.git import WorkspacePolicyError


@runtime_checkable
class ModelInputPreparation(Protocol):
    """Prepare exact material without provider calls or one-use authority writes."""

    def prepare_input(self, request: AgentRequest) -> None: ...

    def discard_prepared_input(self, request: AgentRequest) -> None: ...


class FinalModelInputCapacityExceeded(ContextBudgetExceeded):
    """The actual serialized provider input failed before invocation admission."""

    def __init__(self, *, estimated_input_tokens: int, max_input_tokens: int) -> None:
        self.estimated_input_tokens = estimated_input_tokens
        self.max_input_tokens = max_input_tokens
        super().__init__(
            "final provider input exceeds the configured Context budget "
            f"({estimated_input_tokens} > {max_input_tokens})"
        )


class BoundModelInputBudget:
    """Apply the original typed Context budget to the final serialized model input."""

    def __init__(self, resolver: ContextResolver) -> None:
        self._resolver = resolver

    def check(self, request: AgentRequest, content: str) -> None:
        context = self._resolver.get_context(request.context_manifest_id)
        if (
            context.context_id != request.context_manifest_id
            or context.task_id != request.task_id
            or context.role is not request.role
            or context.attempt != request.attempt
            or context.source_revision != request.source_revision
        ):
            raise WorkspacePolicyError("final provider input Context differs from AgentRequest")
        if any(
            hashlib.sha256(section.content.encode()).hexdigest() != section.sha256
            for section in context.sections
        ):
            raise WorkspacePolicyError("final provider input Context integrity differs")
        tokens = estimate_input_tokens(content)
        if tokens > context.budget.max_input_tokens:
            raise FinalModelInputCapacityExceeded(
                estimated_input_tokens=tokens,
                max_input_tokens=context.budget.max_input_tokens,
            )
