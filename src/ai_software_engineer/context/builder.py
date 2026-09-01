"""Local deterministic Context Builder implementation."""

import hashlib
import json
import re
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

from ai_software_engineer.context.models import (
    ContextBudget,
    ContextBundle,
    ContextRedaction,
    ContextSection,
    ContextSource,
)
from ai_software_engineer.context.ports import (
    ContextBudgetExceeded,
    ContextSourceDenied,
    ContextSourceError,
    ContextSourceNotFound,
)
from ai_software_engineer.context.router import ContextRouter
from ai_software_engineer.domain.agent import AgentPermissions
from ai_software_engineer.domain.enums import AgentRole
from ai_software_engineer.domain.model import WirePayload
from ai_software_engineer.domain.task import Task
from ai_software_engineer.git import PathPolicyViolation, WorkspacePolicy

DEFAULT_CONTEXT_BUDGET: Final[ContextBudget] = ContextBudget(
    max_input_tokens=12_000,
    reserved_output_tokens=4_000,
)
DEFAULT_ROLE_INSTRUCTIONS: Final[dict[AgentRole, str]] = {
    AgentRole.ORCHESTRATOR: "Coordinate the state machine; do not implement business code.",
    AgentRole.CODER: "Implement only the Task acceptance criteria in the assigned worktree.",
    AgentRole.QA: "Independently verify every required acceptance criterion with evidence.",
    AgentRole.REVIEWER: "Review the exact candidate revision read-only and report findings.",
}

_SECRET_PATTERNS: Final[tuple[tuple[str, re.Pattern[str]], ...]] = (
    (
        "private_key",
        re.compile(
            r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----",
            re.DOTALL,
        ),
    ),
    ("openai_key", re.compile(r"\bsk-[A-Za-z0-9][A-Za-z0-9_-]{19,}\b")),
    ("aws_access_key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("github_token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b")),
    (
        "bearer_token",
        re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]{8,}"),
    ),
    (
        "secret_assignment",
        re.compile(
            r"""(?i)(["']?\b(?:password|passwd|secret|token|api[_-]?key)\b["']?\s*[:=]\s*["']?)([^\s,;"'}]+)(["']?)"""
        ),
    ),
)


class FileContextBuilder:
    """Compile declared project sources into a deterministic redacted ContextBundle."""

    def __init__(
        self,
        project_root: str | Path,
        permissions: AgentPermissions,
        *,
        sources: tuple[ContextSource, ...] = (),
        budget: ContextBudget = DEFAULT_CONTEXT_BUDGET,
        role_instructions: Mapping[AgentRole, str] | None = None,
    ) -> None:
        self._project_root = Path(project_root).resolve()
        if not self._project_root.is_dir():
            raise ContextSourceError(f"project root is not a directory: {self._project_root}")
        if any(source.priority == 0 for source in sources):
            raise ContextSourceError("ContextSource priority 0 is reserved for machine policy")
        self._permissions = permissions
        self._sources = sources
        self._budget = budget
        self._role_instructions = dict(DEFAULT_ROLE_INSTRUCTIONS)
        if role_instructions is not None:
            self._role_instructions.update(role_instructions)

    def build(
        self,
        task: Task,
        role: AgentRole,
        *,
        attempt: int,
        candidate_revision: str | None = None,
    ) -> ContextBundle:
        """Route, redact, budget, and hash one role-scoped context bundle."""
        if type(attempt) is not int or not 1 <= attempt <= 10:
            raise ContextSourceError(f"attempt must be between 1 and 10: {attempt}")
        if not isinstance(role, AgentRole):
            raise ContextSourceError(f"unknown Agent role: {role!r}")
        source_revision = task.base_ref if candidate_revision is None else candidate_revision
        _validate_revision(source_revision)
        task_denied_paths = task.constraints.denied_paths if task.constraints else ()
        policy = WorkspacePolicy(
            self._project_root,
            self._permissions,
            denied_paths=task_denied_paths,
        )
        generated = self._generated_sources(task, role, source_revision)
        routed = ContextRouter.route(generated + self._sources, role)
        sections, redactions = self._compile_sections(routed, policy)
        used_tokens = sum(section.tokens for section in sections)
        budget = self._budget.model_copy(update={"used_input_tokens": used_tokens})
        identity_payload: WirePayload = {
            "task_id": task.id,
            "role": role.value,
            "attempt": attempt,
            "source_revision": source_revision,
            "sections": [section.to_wire() for section in sections],
            "redactions": [redaction.to_wire() for redaction in redactions],
            "budget": budget.to_wire(),
        }
        context_id = f"ctx_{_sha256(_canonical_json(identity_payload))}"
        return ContextBundle(
            context_id=context_id,
            task_id=task.id,
            role=role,
            attempt=attempt,
            source_revision=source_revision,
            sections=tuple(sections),
            redactions=tuple(redactions),
            budget=budget,
            built_at=datetime.now(UTC),
        )

    def _generated_sources(
        self, task: Task, role: AgentRole, source_revision: str
    ) -> tuple[ContextSource, ...]:
        policy_payload: WirePayload = {
            "read_paths": list(self._permissions.read_paths),
            "write_paths": list(self._permissions.write_paths),
            "commands": list(self._permissions.commands),
            "network": self._permissions.network.value,
            "can_change_state": self._permissions.can_change_state,
            "can_merge": self._permissions.can_merge,
            "denied_paths": list(task.constraints.denied_paths)
            if task.constraints is not None
            else [],
        }
        generated = [
            ContextSource(
                source_id="policy",
                uri="policy://permissions",
                content=_canonical_json(policy_payload),
                priority=0,
                required=True,
            ),
            ContextSource(
                source_id="task",
                uri=f"task://{task.id}",
                content=_canonical_json(task.to_wire()),
                priority=30,
                required=True,
            ),
            ContextSource(
                source_id="role",
                uri=f"role://{role.value}",
                content=self._role_instructions[role],
                roles=(role,),
                priority=40,
                required=True,
            ),
        ]
        if source_revision != task.base_ref:
            generated.append(
                ContextSource(
                    source_id="candidate",
                    uri=f"git://{source_revision}",
                    content=f"candidate_revision={source_revision}",
                    roles=(role,),
                    priority=50,
                    required=True,
                )
            )
        return tuple(generated)

    def _compile_sections(
        self,
        sources: tuple[ContextSource, ...],
        policy: WorkspacePolicy,
    ) -> tuple[list[ContextSection], list[ContextRedaction]]:
        sections: list[ContextSection] = []
        redactions: list[ContextRedaction] = []
        remaining = self._budget.max_input_tokens
        used_uris: set[str] = set()
        for source in sources:
            safe_uri, uri_redactions = _redact(source.uri, f"source://{source.source_id}")
            if safe_uri in used_uris:
                raise ContextSourceError(f"duplicate ContextSource URI: {safe_uri}")
            used_uris.add(safe_uri)
            redactions.extend(uri_redactions)
            content = self._read_source(source, policy)
            if content is None:
                continue
            redacted, source_redactions = _redact(content, safe_uri)
            redactions.extend(source_redactions)
            source_tokens = _estimate_tokens(redacted)
            truncated = False
            if source_tokens > remaining:
                if source.required:
                    raise ContextBudgetExceeded(
                        f"required ContextSource does not fit budget: {source.source_id}"
                    )
                if remaining == 0:
                    continue
                redacted = _truncate_to_tokens(redacted, remaining)
                source_tokens = _estimate_tokens(redacted)
                truncated = True
            section = ContextSection(
                name=_section_name(source),
                uri=safe_uri,
                sha256=_sha256(redacted),
                tokens=source_tokens,
                content=redacted,
                priority=source.priority,
                truncated=truncated,
            )
            sections.append(section)
            remaining -= source_tokens
        return sections, redactions

    def _read_source(self, source: ContextSource, policy: WorkspacePolicy) -> str | None:
        if source.relative_path is None:
            if source.content is None:
                raise ContextSourceError(f"source has no content: {source.source_id}")
            return source.content
        try:
            normalized = policy.authorize_read(source.relative_path)
        except PathPolicyViolation as error:
            raise ContextSourceDenied(
                f"source path is outside Context read policy: {source.relative_path}"
            ) from error
        path = self._project_root / normalized
        if not path.is_file():
            if source.required:
                raise ContextSourceNotFound(str(path))
            return None
        try:
            return path.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as error:
            raise ContextSourceError(f"cannot read ContextSource {source.uri}") from error


def _section_name(source: ContextSource) -> str:
    if source.source_id in {"policy", "task", "role", "candidate"}:
        return source.source_id
    return f"source:{source.source_id}"


def _redact(content: str, uri: str) -> tuple[str, list[ContextRedaction]]:
    redactions: list[ContextRedaction] = []
    redacted = content
    for kind, pattern in _SECRET_PATTERNS:
        if kind == "secret_assignment":
            replacement = rf"\1[REDACTED:{kind}]\3"
        else:
            replacement = f"[REDACTED:{kind}]"
        redacted, count = pattern.subn(replacement, redacted)
        if count:
            redactions.append(ContextRedaction(uri=uri, kind=kind, count=count))
    return redacted, redactions


def _estimate_tokens(content: str) -> int:
    return (len(content) + 3) // 4


def _truncate_to_tokens(content: str, tokens: int) -> str:
    candidate = content[: tokens * 4]
    while _estimate_tokens(candidate) > tokens:
        candidate = candidate[:-1]
    return candidate


def _validate_revision(revision: str) -> None:
    if (
        not isinstance(revision, str)
        or not revision
        or any(ord(character) < 32 or character.isspace() for character in revision)
    ):
        raise ContextSourceError("source revision must be non-empty and free of control characters")


def _sha256(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _canonical_json(payload: WirePayload) -> str:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
