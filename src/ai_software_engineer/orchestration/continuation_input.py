"""Reading references to a completely verified, retained v2 Coder worktree.

This is not a durable record, capture replacement, or execution admission. The
caller must first verify the full receipt, stop, ownership and current worktree.
"""

import hashlib
import json
from typing import Annotated, Literal

from pydantic import Field, StrictBool, StrictInt

from ai_software_engineer.domain.model import DomainModel
from ai_software_engineer.domain.project_delivery import StageSha256
from ai_software_engineer.git.mutation_capture import RegularMode
from ai_software_engineer.orchestration.continuation_capture import (
    CapturedMutationBody,
    CapturedMutations,
)
from ai_software_engineer.orchestration.continuation_models import (
    ContinuationRejected,
    ContinuationScope,
    ExecutionInterruptionReceipt,
)
from ai_software_engineer.recovery.models import FullCommit, RelativePath, digest


class PreservedBodyReference(DomainModel):
    sha256: StageSha256
    size: Annotated[StrictInt, Field(ge=0)]
    mode: RegularMode

    @classmethod
    def from_body(cls, body: CapturedMutationBody | None) -> "PreservedBodyReference | None":
        return None if body is None else cls(sha256=body.sha256, size=body.size, mode=body.mode)


class PreservedMutationReference(DomainModel):
    path: RelativePath
    before: PreservedBodyReference | None
    after: PreservedBodyReference | None
    deleted: StrictBool


class PreservedWorktreeContinuationInput(DomainModel):
    kind: Literal["preserved_worktree_continuation_input"] = "preserved_worktree_continuation_input"
    schema_version: Literal["v1"] = "v1"
    scope: ContinuationScope
    original_request_sha256: StageSha256
    source_revision: FullCommit
    base_revision: FullCommit
    receipt_sha256: StageSha256
    capture_sha256: StageSha256
    inventory_after_sha256: StageSha256
    patch_sha256: StageSha256
    patch_bytes: Annotated[StrictInt, Field(ge=0)]
    mutations: tuple[PreservedMutationReference, ...]


def preserved_continuation_prompt(receipt: ExecutionInterruptionReceipt) -> str:
    """Render facts after the caller's full, fresh same-worktree admission checks."""
    if receipt.schema_version != "v2" or not isinstance(receipt.capture, CapturedMutations):
        raise ContinuationRejected("preserved worktree input requires a complete v2 capture")
    capture = receipt.capture
    patch = capture.patch.encode("utf-8")
    reading = PreservedWorktreeContinuationInput(
        scope=receipt.scope,
        original_request_sha256=digest(receipt.request.to_wire()),
        source_revision=capture.source_revision,
        base_revision=capture.base_revision or capture.source_revision,
        receipt_sha256=receipt.receipt_sha256,
        capture_sha256=capture.capture_sha256,
        inventory_after_sha256=receipt.inventory_after_sha256,
        patch_sha256=hashlib.sha256(patch).hexdigest(),
        patch_bytes=len(patch),
        mutations=tuple(
            PreservedMutationReference(
                path=item.path,
                before=PreservedBodyReference.from_body(item.before),
                after=PreservedBodyReference.from_body(item.after),
                deleted=item.after is None,
            )
            for item in capture.mutations
        ),
    )
    return (
        "平台已完整核验上次中断回执、实际停止、当前授权与同一工作区的全部保留进度。\n"
        "这是原工作区的新的独立执行; 现存文件就是保留的开发进度, 不是已接纳的 "
        "CoderProgress、候选提交或验收结论。请先用当前允许的 read_file/只读 Git 命令检查"
        "下列路径, 再在原范围内继续; deleted=true 表示文件已删除, mode 是实际权限。\n"
        "完整补丁及变更前后正文仍保存在不可变回执中, 本阅读清单仅避免再次内嵌现存源码。"
        "before 摘要不能还原旧正文或代替审计/重放; 已有 coder_reapply 的完整历史补丁"
        "仍是必需输入, 请继续适配。清单不扩大文件/命令权限, 不允许读取平台 sidecar, "
        "不授权修改规范、直接提交或宣称未经独立验收的通过。\n"
        "PRESERVED_WORKTREE_INPUT="
        + json.dumps(
            reading.model_dump(mode="json"),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    )
