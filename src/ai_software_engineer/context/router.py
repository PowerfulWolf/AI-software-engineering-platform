"""Pure deterministic role routing for declared context sources."""

from ai_software_engineer.context.models import ContextSource
from ai_software_engineer.context.ports import ContextSourceError
from ai_software_engineer.domain.enums import AgentRole


class DeterministicContextRouter:
    """Select sources for one role in stable priority/URI/source order."""

    @staticmethod
    def route(sources: tuple[ContextSource, ...], role: AgentRole) -> tuple[ContextSource, ...]:
        if not isinstance(role, AgentRole):
            raise ContextSourceError(f"unknown Agent role: {role!r}")
        seen: set[str] = set()
        selected: list[ContextSource] = []
        for source in sources:
            if source.source_id in seen:
                raise ContextSourceError(f"duplicate ContextSource ID: {source.source_id}")
            seen.add(source.source_id)
            if not source.roles or role in source.roles:
                selected.append(source)
        selected.sort(key=lambda source: (source.priority, source.uri, source.source_id))
        return tuple(selected)


ContextRouter = DeterministicContextRouter
