"""Reopen immutable preparation lineage without rediscovering a mutable checkout."""

from __future__ import annotations

import os
import stat
from pathlib import Path

from ai_software_engineer.manager.baseline import FileProjectBaselineCompilationStore
from ai_software_engineer.manager.preparation import PrepareProjectResult, PrepareProjectStatus
from ai_software_engineer.manager.store import FileProjectPreparationStore
from ai_software_engineer.repository_workspace import RepositoryWorkspace
from ai_software_engineer.runtime_workspace import (
    RUNTIME_BINDING_NAME,
    RuntimeWorkspaceBinding,
    TeamWorkforceWorkspace,
    _record_read_path,
    load_repository_profile,
)

MAX_SEALED_PREPARATION_BYTES = 8_000_000


def _read_regular(path: Path) -> bytes:
    if any(part.is_symlink() for part in (path, *path.parents)):
        raise ValueError("原始准备记录路径含不安全的符号链接")
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        observed = os.fstat(descriptor)
        if not stat.S_ISREG(observed.st_mode) or observed.st_size > MAX_SEALED_PREPARATION_BYTES:
            raise ValueError("原始准备记录必须是有界普通文件")
        with os.fdopen(descriptor, "rb", closefd=False) as source:
            body = source.read(MAX_SEALED_PREPARATION_BYTES + 1)
        after = os.fstat(descriptor)
        if len(body) != observed.st_size or (
            after.st_dev,
            after.st_ino,
            after.st_size,
            after.st_mtime_ns,
            after.st_ctime_ns,
        ) != (
            observed.st_dev,
            observed.st_ino,
            observed.st_size,
            observed.st_mtime_ns,
            observed.st_ctime_ns,
        ):
            raise ValueError("原始准备记录在读取期间发生变化")
        return body
    finally:
        os.close(descriptor)


def load_sealed_preparation(
    workspace: RepositoryWorkspace,
    preparation_sha256: str,
    *,
    organization: TeamWorkforceWorkspace,
) -> PrepareProjectResult:
    """Read the exact preparation/profile/binding/compilation, never current Git rules."""
    workspace.manifest.validate_binding(workspace.root)
    policy = workspace.directory("policy")
    if any(part.is_symlink() for part in (policy, *policy.parents)):
        raise ValueError("原始准备工作空间路径含不安全的符号链接")
    matches = []
    for directory in (policy, *sorted(policy.glob("preparations-*"))):
        if directory.is_symlink() or not directory.is_dir():
            raise ValueError("原始准备记录目录不安全")
        path = directory / f"project-preparation-{workspace.repository_id}.json"
        if not path.exists() and not path.is_symlink():
            continue
        _read_regular(path)
        preparation = FileProjectPreparationStore(directory, read_only=True).get(
            workspace.repository_id
        )
        if preparation.preparation_sha256 == preparation_sha256:
            matches.append(preparation)
    if len(matches) != 1:
        raise ValueError("原始准备记录缺失或不唯一, 无法恢复已批准上下文")
    prepared = matches[0]
    if (
        prepared.repository_id != workspace.repository_id
        or prepared.repository_root != str(workspace.repository_root)
        or prepared.repository_workspace_root != str(workspace.root)
        or prepared.project_id != workspace.manifest.project_id
        or prepared.project_manifest_sha256 != workspace.manifest.project_manifest_sha256
        or prepared.team_id != organization.team_id
        or prepared.team_root != str(organization.root)
    ):
        raise ValueError("原始准备记录不属于当前 Team、Project 和 Repository")
    profile = load_repository_profile(workspace.root, prepared.repository_profile_sha256)
    if profile.repository_id != workspace.repository_id:
        raise ValueError("原始项目画像不属于当前 Repository")
    binding_path = _record_read_path(policy, RUNTIME_BINDING_NAME, prepared.runtime_binding_sha256)
    binding = RuntimeWorkspaceBinding.model_validate_json(_read_regular(binding_path))
    binding.validate_integrity()
    if (
        binding.binding_sha256 != prepared.runtime_binding_sha256
        or binding.team_id != prepared.team_id
        or binding.team_root != prepared.team_root
        or binding.team_manifest_sha256 != organization.manifest.manifest_sha256
        or binding.project_id != prepared.project_id
        or binding.project_manifest_sha256 != prepared.project_manifest_sha256
        or binding.repository_id != prepared.repository_id
        or binding.repository_root != prepared.repository_root
        or binding.repository_workspace_root != prepared.repository_workspace_root
        or binding.repository_manifest_sha256 != workspace.manifest.manifest_sha256
        or binding.repository_profile_sha256 != prepared.repository_profile_sha256
    ):
        raise ValueError("原始运行工作空间绑定与已批准准备事实不一致")
    compilation_root = policy / "project-baseline-compilations"
    if compilation_root.is_symlink() or not compilation_root.is_dir():
        raise ValueError("原始规范编译记录目录不安全或已缺失")
    store = FileProjectBaselineCompilationStore()
    compilations = []
    for path in sorted(compilation_root.glob("*.json")):
        _read_regular(path)
        record = store.get(workspace, path.stem)
        if (
            record.repository_profile_sha256 == prepared.repository_profile_sha256
            and record.compiled_spec is not None
            and record.compiled_spec.baseline_sha256 == prepared.baseline_spec_sha256
            and record.compiled_spec.source_uris == prepared.baseline_source_uris
        ):
            compilations.append(record)
    if len(compilations) != 1:
        raise ValueError("原始规范编译记录缺失或不唯一")
    return PrepareProjectResult(
        status=PrepareProjectStatus.PREPARED,
        repository_id=workspace.repository_id,
        preparation=prepared,
        baseline_compilation_sha256=compilations[0].compilation_sha256,
    )
