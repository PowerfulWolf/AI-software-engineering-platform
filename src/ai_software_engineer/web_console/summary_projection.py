"""Bounded read-side cache; no complete operation or execution decision survives."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from .models import ConsoleOperation
from .summary_models import (
    MAX_ACTIVE_SUMMARIES,
    MAX_SUMMARY_PAGE_BYTES,
    OperationSummary,
    OperationSummaryCursor,
    OperationSummaryPage,
    OperationSummaryQuery,
    StaleOperationCursor,
)


class SummaryProjectionUnavailable(ValueError):
    """A complete, bounded reading page cannot be published safely."""


@dataclass(frozen=True)
class _CachedSummary:
    inventory_sha256: str
    summary: OperationSummary
    retained_bytes: int


class OperationSummaryCache:
    """Only use after a fresh full-byte inventory under the store's shared lock."""

    def __init__(self, *, maximum_entries: int = 512, maximum_bytes: int = 2 * 1024 * 1024) -> None:
        self.maximum_entries = maximum_entries
        self.maximum_bytes = maximum_bytes
        self.entries: dict[str, _CachedSummary] = {}
        self.retained_bytes = 0

    def discard_absent(self, operation_ids: set[str]) -> None:
        for operation_id in tuple(self.entries):
            if operation_id not in operation_ids:
                self._discard(operation_id)

    def project(
        self, operation_id: str, inventory_sha256: str, read: Callable[[], ConsoleOperation | None]
    ) -> OperationSummary | None:
        entry = self.entries.get(operation_id)
        if entry is not None and entry.inventory_sha256 == inventory_sha256:
            return entry.summary
        self._discard(operation_id)
        operation = read()
        if operation is None:
            return None
        summary = OperationSummary.from_operation(operation)
        # Include retained inventory and key bytes in the serialized footprint.
        size = (
            len(summary.model_dump_json().encode())
            + len(operation_id.encode())
            + len(inventory_sha256.encode())
        )
        if (
            len(self.entries) < self.maximum_entries
            and self.retained_bytes + size <= self.maximum_bytes
        ):
            self.entries[operation_id] = _CachedSummary(inventory_sha256, summary, size)
            self.retained_bytes += size
        return summary

    def _discard(self, operation_id: str) -> None:
        old = self.entries.pop(operation_id, None)
        if old is not None:
            self.retained_bytes -= old.retained_bytes


def build_summary_page(
    *,
    summaries: tuple[OperationSummary, ...],
    inventory_sha256: str,
    query: OperationSummaryQuery,
    team_id: str,
) -> OperationSummaryPage:
    if any(item.team_id != team_id for item in summaries):
        raise SummaryProjectionUnavailable("operation summary Team differs")
    current = tuple(
        sorted(
            (
                item
                for item in summaries
                if (query.project_id is None or item.project_id == query.project_id)
                and (query.delivery_id is None or item.delivery_id == query.delivery_id)
            ),
            key=lambda item: (item.requested_at, item.operation_id),
            reverse=True,
        )
    )
    active = tuple(item for item in current if item.active)
    if len(active) > MAX_ACTIVE_SUMMARIES:
        raise SummaryProjectionUnavailable("operation active summary bound exceeded")
    offset = 0
    if query.cursor is not None:
        cursor = OperationSummaryCursor.decode(query.cursor)
        if (
            cursor.inventory_sha256 != inventory_sha256
            or cursor.scope != query.scope
            or cursor.page_size != query.page_size
        ):
            raise StaleOperationCursor("operation summary history changed")
        anchor = (cursor.after_requested_at, cursor.after_operation_id)
        position = next(
            (
                index
                for index, item in enumerate(current)
                if (item.requested_at, item.operation_id) == anchor
            ),
            None,
        )
        if position is None:
            raise StaleOperationCursor("operation summary cursor anchor changed")
        offset = position + 1
    items = current[offset : offset + query.page_size]
    next_cursor = None
    if offset + len(items) < len(current):
        last = items[-1]
        next_cursor = OperationSummaryCursor(
            inventory_sha256=inventory_sha256,
            scope=query.scope,
            page_size=query.page_size,
            after_requested_at=last.requested_at,
            after_operation_id=last.operation_id,
        ).encode()
    page = OperationSummaryPage(
        team_id=team_id,
        scope=query.scope,
        inventory_sha256=inventory_sha256,
        items=items,
        next_cursor=next_cursor,
        total_count=len(current),
        active=active,
    )
    if len(page.model_dump_json().encode()) > MAX_SUMMARY_PAGE_BYTES:
        raise SummaryProjectionUnavailable("operation summary page bound exceeded")
    return page
