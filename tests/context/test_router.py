"""Public-seam tests for deterministic role routing."""

import pytest

from ai_software_engineer.context import ContextRouter, ContextSource, ContextSourceError
from ai_software_engineer.domain import AgentRole


def test_router_filters_role_sources_and_orders_independently_of_input_order() -> None:
    sources = (
        ContextSource(
            source_id="review-only",
            uri="artifact://review",
            content="review evidence",
            roles=(AgentRole.REVIEWER,),
            priority=50,
        ),
        ContextSource(
            source_id="common-late",
            uri="docs/common.md",
            content="common project facts",
            priority=20,
        ),
        ContextSource(
            source_id="coder-only",
            uri="artifact://qa",
            content="qa finding",
            roles=(AgentRole.CODER,),
            priority=40,
        ),
        ContextSource(
            source_id="common-early",
            uri="AGENTS.md",
            content="organization policy",
            priority=0,
        ),
    )

    coder = ContextRouter.route(sources, AgentRole.CODER)
    reviewer = ContextRouter.route(tuple(reversed(sources)), AgentRole.REVIEWER)

    assert tuple(source.source_id for source in coder) == (
        "common-early",
        "common-late",
        "coder-only",
    )
    assert tuple(source.source_id for source in reviewer) == (
        "common-early",
        "common-late",
        "review-only",
    )


def test_router_rejects_unknown_role() -> None:
    source = ContextSource(source_id="common", uri="docs/common.md", content="facts")

    with pytest.raises(ContextSourceError, match="unknown Agent role"):
        ContextRouter.route((source,), "coder")  # type: ignore[arg-type]
