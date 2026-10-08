"""Validate all current legacy files, including ignored entries, before rescue.

Git capture verifies tracked/index flags and all visible mutations. The separate
inventory must also reject uncaptured ignored input; only explicit existing
execution caches may be retained outside the complete code snapshot.
"""

from ai_software_engineer.git import GitWorktreeManager
from ai_software_engineer.git.mutation import WorkspaceMutationInventory, is_execution_cache_path
from ai_software_engineer.orchestration.continuation_capture import CapturedMutations


def require_complete_legacy_inventory(
    git: GitWorktreeManager,
    capture: CapturedMutations,
    inventory: WorkspaceMutationInventory,
) -> None:
    tree = git._run_git_bytes(
        ("ls-tree", "-r", "-z", capture.source_revision), cwd=capture.to_capture().worktree.path
    )
    tracked: set[str] = set()
    for record in tree.split(b"\0"):
        if not record:
            continue
        metadata, separator, raw_path = record.partition(b"\t")
        if not separator:
            raise ValueError("原代码文件清单无法校验, 保留现场")
        mode, kind, _ = metadata.decode("ascii").split(" ")
        if mode not in {"100644", "100755"} or kind != "blob":
            raise ValueError("旧现场包含不受支持的链接或子仓库, 保留现场")
        tracked.add(raw_path.decode("utf-8"))
    mutations = {item.path: item for item in capture.mutations}
    present = {item.path: item for item in inventory.files if item.path != ".git"}
    for path, item in present.items():
        if item.kind != "file":
            raise ValueError("旧现场包含链接或非普通文件, 不能直接继续, 保留现场")
        mutation = mutations.get(path)
        if mutation is not None:
            after = mutation.after
            if after is None or (after.sha256, after.size, after.mode) != (
                item.sha256,
                item.size,
                item.mode,
            ):
                raise ValueError("保留草稿与完整文件清单不一致, 保留现场")
        elif path not in tracked and not is_execution_cache_path(path):
            raise ValueError("旧现场包含未纳入完整草稿的忽略文件, 需要平台维护处理; 不会删除原文件")
    for path in tracked | mutations.keys():
        mutation = mutations.get(path)
        if path not in present and (mutation is None or mutation.after is not None):
            raise ValueError("旧现场缺少未封存的原代码文件, 保留现场")
