"""Resolve successor native bodies from the exact already-approved Git profile."""

import hashlib
import json
import os
import re
import subprocess
from pathlib import Path, PurePosixPath
from urllib.parse import urlparse

from ai_software_engineer.context.models import ContextBundle, ContextSource
from ai_software_engineer.context.ports import ContextSourceError
from ai_software_engineer.domain.execution_native_rules import NativeRuleEpoch
from ai_software_engineer.redaction import redact_text
from ai_software_engineer.repository_profile import RepositoryProfile


def native_rule_epoch_context_source(epoch: NativeRuleEpoch) -> ContextSource:
    """Required compact provenance; full approved bodies remain separate sources."""
    epoch.validate_integrity()
    content = json.dumps(
        {
            "epoch": epoch.reference.to_wire(),
            "instructions": (
                "本次执行采用精确批准的目标版本原生规范。"
                "目标原生规范正文替代原准备记录中的旧原生文档引用; "
                "原 Product 范围、平台硬策略、显式结构化规范和执行权限仍保持。"
                "工程批准不允许 Agent 修改权限或绕过独立 QA/Review。"
            ),
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return ContextSource(
        source_id="execution.native_rules",
        uri="native-rules://" + epoch.epoch_sha256,
        content=content,
        required=True,
        priority=15,
    )


def execution_native_rule_sources(
    sources: tuple[ContextSource, ...],
    epoch: NativeRuleEpoch,
    *,
    profile: RepositoryProfile,
) -> tuple[ContextSource, ...]:
    """Replace the complete native set, including newly added/deleted documents.

    Sources are already sealed Git bodies; this function performs no checkout I/O.
    Original preparation and Product inputs are never modified. Matching native
    entries retain their role routing; newly discovered rules apply to all roles.
    """
    epoch.validate_integrity()
    profile.validate_integrity()
    if profile.repository_id != epoch.scope.repository_id:
        raise ContextSourceError("原生规范版本与原批准的 Repository 不一致")
    native: dict[str, ContextSource] = {}
    retained = []
    for source in sources:
        if source.source_id == "execution.native_rules":
            if source != native_rule_epoch_context_source(epoch):
                raise ContextSourceError("原生规范上下文已绑定不同的执行版本")
            continue
        if not source.source_id.startswith(("native.rule.", "native.reference.")):
            retained.append(source)
            continue
        if not source.uri.startswith(f"project://{epoch.scope.repository_id}/"):
            raise ContextSourceError("原生规范上下文含有其他 Repository 的来源")
        if source.uri in native:
            raise ContextSourceError("原生规范上下文来源重复")
        native[source.uri] = source
    for body in epoch.bodies:
        previous = native.get(body.source.uri)
        identity = (
            "native.rule." + hashlib.sha256(body.source.relative_path.encode()).hexdigest()[:32]
        )
        retained.append(
            ContextSource(
                source_id=identity,
                uri=body.source.uri,
                content=body.content,
                roles=previous.roles if previous is not None else (),
                priority=previous.priority if previous is not None else 100,
                required=True,
            )
        )
    retained.append(native_rule_epoch_context_source(epoch))
    return tuple(retained)


def validate_native_rule_epoch_context(
    context: ContextBundle,
    epoch: NativeRuleEpoch,
    *,
    expected_sources: tuple[ContextSource, ...] | None = None,
) -> None:
    """Verify the sealed provenance and each delivered native body/reference."""
    source = native_rule_epoch_context_source(epoch)
    markers = tuple(
        section for section in context.sections if section.name == "source:execution.native_rules"
    )
    if len(markers) != 1 or source.content is None:
        raise ContextSourceError("执行上下文缺少唯一、完整的已批准原生规范版本")
    marker = markers[0]
    if (
        marker.truncated
        or marker.uri != source.uri
        or marker.content != source.content
        or marker.sha256 != hashlib.sha256(source.content.encode()).hexdigest()
    ):
        raise ContextSourceError("执行上下文的原生规范版本与可信批准记录不一致")
    bodies = {body.source.uri: body for body in epoch.bodies}
    native_sections = tuple(
        section
        for section in context.sections
        if section.name.startswith(("source:native.rule.", "source:native.reference."))
    )
    if expected_sources is not None:
        applicable = {
            source.uri
            for source in expected_sources
            if source.source_id.startswith(("native.rule.", "native.reference."))
            and (not source.roles or context.role in source.roles)
        }
        if {section.uri for section in native_sections} != applicable:
            raise ContextSourceError("执行上下文缺少该角色所需的完整目标原生规范清单")
    for section in native_sections:
        body = bodies.get(section.uri)
        if body is None or section.truncated:
            raise ContextSourceError("执行上下文含有旧原生规范或不完整目标规范")
        full = ContextSource(
            source_id="native.rule.verified", uri=section.uri, content=body.content
        )
        expected = (
            native_rule_prompt_sources((full,))[0].content
            if section.name.startswith("source:native.reference.")
            else body.content
        )
        if (
            section.content != expected
            or hashlib.sha256(section.content.encode()).hexdigest() != section.sha256
        ):
            raise ContextSourceError("执行上下文原生规范正文与已批准目标版本不一致")


def native_rule_prompt_sources(sources: tuple[ContextSource, ...]) -> tuple[ContextSource, ...]:
    """Project frozen rules for a prompt paired with active knowledge retrieval.

    The knowledge snapshot must still consume the original sources. Preserve all
    AGENTS instructions; other bodies remain available in the frozen search/read
    corpus. This projection is never persisted back into approved preparation.
    """
    projected = []
    for source in sources:
        if not source.source_id.startswith("native.rule."):
            projected.append(source)
            continue
        if source.content is None:
            raise ContextSourceError("native prompt projection requires frozen inline content")
        if PurePosixPath(urlparse(source.uri).path).name.lower() == "agents.md":
            projected.append(source)
            continue
        safe = redact_text(source.content).text
        content = (
            "Project-native rule reference; full body remains in the frozen knowledge snapshot. "
            f"URI={redact_text(source.uri).text}; "
            f"frozen_redacted_sha256={hashlib.sha256(safe.encode('utf-8')).hexdigest()}. "
            "Consult applicable rules before editing or verifying. Verified retrieved passages "
            "are supplied in knowledge.reads; references alone do not supply the rule text. "
            "Report missing required rules rather than inferring their contents."
        )
        projected.append(
            source.model_copy(
                update={
                    "source_id": source.source_id.replace("native.rule.", "native.reference.", 1),
                    "content": content,
                }
            )
        )
    return tuple(projected)


def rebind_native_rule_sources(
    repository_root: Path,
    profile: RepositoryProfile,
    sources: tuple[ContextSource, ...],
    *,
    source_revision: str | None = None,
) -> tuple[ContextSource, ...]:
    """Keep source scopes/identity, but use the successor's sealed native revision.

    Recovery can approve a newer preparation than the original Requirement. Its
    baseline cannot be paired with the parent's older native bodies. No current
    checkout reads, historical record writes, or changed-hash exceptions are allowed.
    Absent bodies stay absent so historical omissions remain explicit.
    """
    profile.validate_integrity()
    if not any(source.source_id.startswith("native.rule.") for source in sources):
        return sources
    revision = source_revision or profile.vcs.revision
    if revision is None or re.fullmatch(r"[a-f0-9]{40}|[a-f0-9]{64}", revision) is None:
        raise ValueError("native rule requires a sealed Git revision")
    if profile.vcs.revision not in {None, "unknown", revision}:
        raise ValueError("native rule revision differs from the sealed profile")
    references = {item.uri: item for item in profile.native_rules}
    result = []
    for source in sources:
        if not source.source_id.startswith("native.rule."):
            result.append(source)
            continue
        reference = references.get(source.uri)
        if reference is None:
            raise ValueError("native rule is not in the sealed profile")
        if reference.byte_length > 256_000:
            raise ValueError("native rule exceeds context limit")
        object_name = f"{revision}:{reference.relative_path}"
        size = _git_object(repository_root, "-s", object_name)
        if size.strip() != str(reference.byte_length).encode("ascii"):
            raise ValueError("native rule differs from the sealed profile")
        data = _git_object(repository_root, "blob", object_name)
        if (
            len(data) != reference.byte_length
            or hashlib.sha256(data).hexdigest() != reference.sha256
        ):
            raise ValueError("native rule differs from the sealed profile")
        content = redact_text(data.decode("utf-8")).text
        result.append(source.model_copy(update={"content": content, "relative_path": None}))
    return tuple(result)


def _git_object(root: Path, mode: str, object_name: str) -> bytes:
    try:
        result = subprocess.run(
            (
                "git",
                "-c",
                "core.hooksPath=/dev/null",
                "-c",
                "core.fsmonitor=false",
                "cat-file",
                mode,
                object_name,
            ),
            cwd=root,
            env={
                "PATH": os.defpath,
                "LANG": "C",
                "LC_ALL": "C",
                "GIT_CONFIG_NOSYSTEM": "1",
                "GIT_TERMINAL_PROMPT": "0",
                "GIT_NO_REPLACE_OBJECTS": "1",
            },
            capture_output=True,
            check=False,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise ValueError("sealed native rule could not be read") from error
    if result.returncode:
        raise ValueError("sealed native rule could not be read")
    return result.stdout
