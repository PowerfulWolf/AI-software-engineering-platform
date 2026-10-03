"""Chinese read-side wording for durable delivery blockage facts.

The journal, Task and Operation records intentionally keep their original bytes.  This
module is only a presentation adapter: it recognizes the stable platform messages that
predate the Chinese console and leaves identifiers, digests and error codes intact.
"""

from __future__ import annotations

import re

# The Chinese UI copy intentionally uses full-width punctuation.
# ruff: noqa: E501, RUF001


_EXACT: dict[str, str] = {
    "REQUEST_HUMAN": "需要人工处理后再继续交付。",
    "A child delivery or integration requires recovery.": "子交付或联合集成需要恢复。",
    (
        "Delivery is blocked by a child delivery or integration requiring recovery. "
        "The child finding requests human involvement; no repair or usable approval is "
        "established by the supplied hashes alone."
    ): "子交付或联合集成需要恢复，当前交付已阻塞。子任务发现需要人工介入；仅凭现有摘要无法建立可用修复或批准。",
    (
        "Required context exceeds the configured input budget; no model retry."
    ): "所需上下文超过配置的输入上限，不能重试模型。",
    (
        "BUDGET_EXHAUSTED: Required context exceeds the configured input budget; "
        "no automatic retry."
    ): "BUDGET_EXHAUSTED：所需上下文超过配置的输入上限，不能自动重试。",
    "Coder requested continuation after the configured run budget": "Coder 已用完本轮连续执行次数，但实现尚未完成，需要创建恢复任务后继续。",
    "QA verification could not complete in the current environment": "QA 未能在当前环境完成验证；候选代码已保留，继续交付时只会重新执行 QA/Review。",
    "Candidate verification stopped before a sealed result was produced.": "候选验证在封存结果生成前停止。",
    "Candidate verification passed; continue the delivery acceptance policy.": "候选验证已通过，请继续执行交付验收策略。",
    "Continue the delivery to create and approve a fresh verification plan.": "请继续交付，以创建并批准新的验证计划。",
    "A successor verification plan replaced this consumed plan.": "后续验证计划已替代本次已消费的计划。",
    "QA candidate verification is active or awaiting resume.": "QA 候选验证正在执行或等待恢复。",
    "Reviewer candidate verification is active or awaiting resume.": "Reviewer 候选验证正在执行或等待恢复。",
    "Verify the complete pinned candidate set together.": "请对已固定的完整候选集合执行联合验证。",
    "Joint integration failed. Preserve candidates and inspect command evidence; do not merge independently.": "联合集成失败。请保留候选并检查命令证据，不要单独合并。",
    "Joint candidates passed repository QA/Review and integration. Review the candidate set before merging; nothing was pushed.": "所有候选已通过仓库 QA、Review 和联合集成。合并前请检查候选集合；平台没有推送代码。",
    "The repository candidate passed native QA and Review. Review the candidate before merging; nothing was pushed.": "仓库候选已通过原生 QA 和 Review。合并前请检查候选；平台没有推送代码。",
    "Resume only incomplete repository deliveries.": "仅恢复尚未完成的仓库交付。",
    "No automatic continuation is available; inspect the terminal Task and use explicit recovery if it contains uncommitted Coder work.": "当前没有可自动继续的路径；请检查终态 Task，如有未提交的 Coder 改动则使用明确的恢复流程。",
    "Review and approve the exact Coder recovery plan.": "请检查并批准精确的 Coder 恢复计划。",
    "Review and approve the exact omitted file paths.": "请检查并批准精确的遗漏文件路径。",
    "Approve one new Coder Run on the exact stopped workspace.": "请在已停止的精确工作区上批准一次新的 Coder 执行。",
    "Approve the exact omitted file paths before capturing retained work.": "请先批准精确的遗漏文件路径，再封存保留的改动。",
    "Inspect the captured Coder changes, then rerun request resume with this exact plan digest and an approval reference.": "请检查已封存的 Coder 改动，然后携带该精确计划摘要和批准引用重新请求恢复。",
    "Waiting for recovery": "等待恢复。",
    "Current recovery source or target facts do not match": "当前恢复来源或目标事实不匹配。",
    "Manager operation failed; inspect durable delivery facts.": "Manager 操作失败，请检查持久化的交付事实。",
    "Manager rejected the operation; inspect current delivery facts.": "Manager 拒绝了该操作，请检查当前交付事实。",
    "The previous joint integration command failed. Produce a fresh, complete integration plan using the recorded command evidence.": "上一次联合集成命令失败。请依据已记录的命令证据生成新的完整联合集成计划。",
}

_REPOSITORY_BLOCKED = re.compile(
    r"^Repository (?P<repository>.+?) is BLOCKED; (?P<detail>.*)$"
)
_ROLE_FAILURE = re.compile(
    r"^(?:TRANSIENT_INFRA:\s*)?(?P<role>Coder|QA|Reviewer) failed at attempt "
    r"(?P<attempt>\d+): (?P<detail>.*)$"
)
_KNOWLEDGE_FAILURE = re.compile(
    r"^(?P<role>coder|qa|reviewer) knowledge "
    r"(?P<phase>preparation|assessment|intent) failed:\s*"
    r"(?P<code>[A-Z0-9_:-]+)$",
    re.IGNORECASE,
)


def _repository_blocker(text: str) -> str | None:
    match = _REPOSITORY_BLOCKED.fullmatch(text)
    if match is None:
        return None
    repository = match.group("repository")
    detail = match.group("detail").strip()
    if detail == (
        "inspect its native checkpoint. Completed repositories are retained; "
        "joint delivery is not DONE."
    ):
        return f"代码仓库 {repository} 已阻塞；已完成的仓库会保留，联合交付尚未完成。"
    if detail.startswith("PLANNING (INVARIANT_VIOLATION): Planner stopped safely"):
        return f"代码仓库 {repository} 已阻塞；计划阶段校验失败（INVARIANT_VIOLATION），Planner 已安全停止。"
    return f"代码仓库 {repository} 已阻塞；请检查该仓库的交付检查点。"


def _role_failure(text: str) -> str | None:
    match = _ROLE_FAILURE.fullmatch(text)
    if match is None:
        return None
    role, attempt, detail = match.group("role"), match.group("attempt"), match.group("detail")
    run_id = re.search(r"\brun_[0-9a-z]+\b", detail)
    digests = re.findall(r"\b[0-9a-f]{64}\b", detail)
    if "failed provider route left repository changes" in detail:
        reason = "提供方路由失败后仓库仍有改动"
    elif "Codex CLI provider execution failed" in detail:
        reason = "Codex CLI 模型服务执行失败"
    else:
        reason = "执行失败，原始诊断已封存"
    facts = [f"执行记录 {run_id.group(0)}"] if run_id else []
    facts.extend(f"证据摘要 {digest}" for digest in digests[:2])
    suffix = "；".join(facts)
    return f"{role} 第 {attempt} 次执行失败：{reason}" + (f"；{suffix}" if suffix else "") + "。"


def _knowledge_failure(text: str) -> str | None:
    match = _KNOWLEDGE_FAILURE.fullmatch(text)
    if match is None:
        return None
    role = {"coder": "Coder", "qa": "QA", "reviewer": "Reviewer"}[
        match.group("role").lower()
    ]
    phase = {
        "preparation": "准备",
        "assessment": "评估",
        "intent": "意图分析",
    }[match.group("phase").lower()]
    code = match.group("code").upper()
    return f"{role} 知识{phase}失败（原因代码：{code}），请检查模型服务后再继续。"


def localize_blocking_text(value: str | None) -> str | None:
    """Return Chinese console wording while preserving safe opaque identifiers."""

    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return text
    exact = _EXACT.get(text)
    if exact is not None:
        return exact
    repository = _repository_blocker(text)
    if repository is not None:
        return repository
    role_failure = _role_failure(text)
    if role_failure is not None:
        return role_failure
    knowledge_failure = _knowledge_failure(text)
    if knowledge_failure is not None:
        return knowledge_failure
    if text.startswith("Coder recovery stopped safely:"):
        return "Coder 恢复已安全停止，请检查失败记录和恢复证据后再继续。"
    if text.startswith("Coder 恢复已安全停止："):
        return "Coder 恢复已安全停止，请检查失败记录和恢复证据后再继续。"
    if text.startswith("Pre-execution restart stopped safely:"):
        return "Coder 启动前重启已安全停止，请检查失败记录和恢复证据后再继续。"
    if text.startswith("Coder 启动前重启已安全停止："):
        return "Coder 启动前重启已安全停止，请检查失败记录和恢复证据后再继续。"
    if text.startswith("Coder recovery contains an unsafe changed path"):
        return "Coder 恢复包含不安全的改动路径，平台已拒绝本次恢复。"
    if text.startswith("failed Coder identity is missing, unsafe or ambiguous") or text.startswith(
        "recoverable Coder identity is missing, unsafe or ambiguous"
    ):
        return "系统未能确认唯一且可信的 Coder 执行记录，本次自动恢复已安全停止。"
    if text.startswith("QA verification could not complete in the current environment"):
        return _EXACT["QA verification could not complete in the current environment"]
    if text.startswith("Rejected plan "):
        return "计划未通过校验，阶段已阻塞；请在恢复时修正计划并保留原错误证据。"
    if text.startswith("SPEC_CONFLICT"):
        return "项目规范与平台安全策略冲突，需要人工决定后才能继续。"
    if text.startswith("Manager:"):
        return "Manager 协调：请检查当前前提并完成恢复。"
    if text.startswith("Repository ") and " is BLOCKED" in text:
        return "代码仓库任务已阻塞，请检查对应交付检查点。"
    if text.startswith("Approve "):
        return "请批准精确的恢复计划后继续。"
    if text.startswith("Review and approve "):
        return "请检查并批准精确计划后继续。"
    if text.startswith("Inspect "):
        return "请检查当前交付记录和证据后再继续。"
    if text.startswith("Continue "):
        return "请继续交付以恢复当前流程。"
    return text


__all__ = ["localize_blocking_text"]
