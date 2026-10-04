"""Public failure contracts for multi-directory Requirement delivery."""

from typing import Literal


class RequirementGitBaselineRequired(ValueError):
    """Selected source lacks the immutable Git baseline required by intake."""

    def __init__(
        self,
        repository_root: str,
        *,
        reason: Literal["not_git", "no_commit", "not_recorded"],
    ) -> None:
        self.repository_root = repository_root
        self.reason = reason
        directory = repository_root if len(repository_root) <= 240 else "…" + repository_root[-239:]
        explanations = {
            "not_git": (
                "所选目录未受 Git 管理。请先初始化 Git 并完成首次提交, 或选择已有提交的 Git 仓库"
            ),
            "no_commit": "所选 Git 仓库没有可用的提交基线 (HEAD)。请先完成首次有效提交",
            "not_recorded": "此需求未记录 Git 提交基线。请使用当前已有提交的目录",
        }
        super().__init__(f"{explanations[reason]}, 然后重新创建需求。目录: {directory}")


class RequirementSourceRevisionDrift(ValueError):
    """A Requirement cannot continue after one of its pinned Git revisions changes."""


class RequirementPreparationContextExceeded(ValueError):
    """Frozen source storage exceeded its bounded size before any model invocation."""

    def __init__(self, *, actual_bytes: int, limit_bytes: int) -> None:
        self.actual_bytes = actual_bytes
        self.limit_bytes = limit_bytes
        super().__init__(
            f"项目规范冻结数据超过存储上限 ({actual_bytes} 字节, 上限 {limit_bytes} 字节)。"
            "请检查规范大小和所选范围后重新创建需求; 平台未截断规范或启动模型。"
        )


__all__ = [
    "RequirementGitBaselineRequired",
    "RequirementPreparationContextExceeded",
    "RequirementSourceRevisionDrift",
]
