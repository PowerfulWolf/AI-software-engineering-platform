"""Complete immutable baseline prefixes owned by one read-only Team projection."""

from dataclasses import dataclass, field
from pathlib import Path

from ai_software_engineer.domain.execution_baseline import ExecutionBaselineBinding
from ai_software_engineer.manager.baseline_store import FileExecutionBaselineStore


@dataclass(slots=True, weakref_slot=True)
class BaselineBindingSnapshot:
    """Share successful full checks, never current execution authorization.

    The next HTTP snapshot owns a new instance and verifies every source again.
    Callers still validate Task/scope/receipt and current SQL queue facts themselves.
    """

    _bindings: dict[tuple[Path, str], tuple[ExecutionBaselineBinding, ...]] = field(
        default_factory=dict
    )

    def bindings_for_task(
        self, store: FileExecutionBaselineStore, task_id: str
    ) -> tuple[ExecutionBaselineBinding, ...]:
        if not store.read_only:
            raise ValueError("baseline read snapshot requires a read-only store")
        identity = (store.root.absolute(), task_id)
        if identity not in self._bindings:
            self._bindings[identity] = store.bindings_for_task(task_id)
        return self._bindings[identity]
