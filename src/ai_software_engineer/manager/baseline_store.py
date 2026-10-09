"""Private append-only baseline plans, decisions, operation starts and bindings."""

from __future__ import annotations

import fcntl
import hashlib
import os
import stat
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from ai_software_engineer.domain.engineering_authority import (
    EngineeringAdmission,
    EngineeringCapability,
)
from ai_software_engineer.domain.execution_baseline import (
    BaselineContinuationMode,
    BaselinePurpose,
    ExecutionBaselineBinding,
)
from ai_software_engineer.domain.execution_native_rules import NativeRuleEpoch
from ai_software_engineer.knowledge.store import KnowledgeRecordStore
from ai_software_engineer.manager.baseline_models import (
    BaselineOperationStart,
    BaselineOperatorAuthorization,
    ExecutionBaselinePlan,
)
from ai_software_engineer.manager.baseline_native_rules import load_native_rule_epoch
from ai_software_engineer.manager.engineering_authority import EngineeringAuthority


class FileExecutionBaselineStore:
    def __init__(self, root: Path, *, read_only: bool = False) -> None:
        if any(path.is_symlink() for path in (root, *root.parents)):
            raise ValueError("baseline store cannot contain symlinks")
        if not read_only:
            root.mkdir(mode=0o700, parents=True, exist_ok=True)
        if stat.S_IMODE(root.stat().st_mode) & 0o077:
            raise ValueError("baseline store must be private")
        self.records = KnowledgeRecordStore(root, read_only=read_only)
        self.root, self.read_only = root, read_only

    @contextmanager
    def execution_lock(self) -> Iterator[None]:
        if self.read_only:
            raise ValueError("read-only baseline store cannot execute")
        directory = self.records._open()
        descriptor = os.open(
            "execution.lock",
            os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK,
            0o600,
            dir_fd=directory,
        )
        try:
            metadata = os.fstat(descriptor)
            if not stat.S_ISREG(metadata.st_mode) or metadata.st_mode & 0o077:
                raise ValueError("baseline lock must be private regular data")
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            yield
            self.records._check_ancestry()
        finally:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
            os.close(descriptor)
            os.close(directory)

    def put_plan(self, plan: ExecutionBaselinePlan) -> ExecutionBaselinePlan:
        plan.validate_integrity()
        return self.records.put("baseline-plans", plan.plan_sha256, plan)

    def plan(self, sha256: str) -> ExecutionBaselinePlan:
        plan = self.records.get("baseline-plans", sha256, ExecutionBaselinePlan)
        plan.validate_integrity()
        if plan.plan_sha256 != sha256:
            raise ValueError("baseline plan key changed")
        return plan

    def native_rule_epoch(self, sha256: str) -> NativeRuleEpoch:
        return load_native_rule_epoch(self.records, sha256)

    def put_authority(
        self, authority: EngineeringAdmission | BaselineOperatorAuthorization
    ) -> None:
        authority.validate_integrity()
        self.records.put("baseline-authorities", authority.plan_sha256, authority)

    def put_start(self, start: BaselineOperationStart) -> BaselineOperationStart:
        start.validate_integrity()
        return self.records.put("baseline-starts", start.plan.plan_sha256, start)

    def start(self, plan_sha256: str) -> BaselineOperationStart | None:
        start = self.records.find("baseline-starts", plan_sha256, BaselineOperationStart)
        if start is not None:
            start.validate_integrity()
        return start

    def bindings_for_task(self, task_id: str) -> tuple[ExecutionBaselineBinding, ...]:
        all_records = self.records.list("baseline-bindings", ExecutionBaselineBinding)
        selected = tuple(
            sorted(
                (item for item in all_records if item.task_id == task_id),
                key=lambda value: value.sequence,
            )
        )
        previous = None
        for item in selected:
            item.require_predecessor(previous)
            plan = self.plan(item.plan_sha256)
            start = self.start(item.plan_sha256)
            if (
                start is None
                or start.plan != plan
                or (start.authority_source, start.authority_sha256)
                != (
                    item.authority_source,
                    item.authority_sha256,
                )
            ):
                raise ValueError("baseline binding has no exact admitted operation")
            if plan.facts.facts_sha256 != item.facts_sha256:
                raise ValueError("baseline binding changed its source facts")
            self._require_authorized_binding(item, plan, previous)
            self.required_context(item)
            previous = item
        return selected

    def put_binding(self, binding: ExecutionBaselineBinding) -> ExecutionBaselineBinding:
        existing = self.bindings_for_task(binding.task_id)
        matched = next((item for item in existing if item.sequence == binding.sequence), None)
        if matched is not None:
            if matched != binding:
                raise ValueError("baseline sequence already has different immutable facts")
            return matched
        binding.require_predecessor(existing[-1] if existing else None)
        self._require_authorized_binding(
            binding, self.plan(binding.plan_sha256), existing[-1] if existing else None
        )
        self.required_context(binding)
        return self.records.put(
            "baseline-bindings", f"{binding.task_id}:{binding.sequence}", binding
        )

    def patch_uri(self, plan_sha256: str) -> str:
        return (
            self.root / self.records._name("baseline-plans", plan_sha256)
        ).absolute().as_uri() + "#complete_capture.patch"

    def _require_authorized_binding(
        self,
        binding: ExecutionBaselineBinding,
        plan: ExecutionBaselinePlan,
        previous: ExecutionBaselineBinding | None,
    ) -> None:
        self._require_rescue_binding(binding, plan)
        if binding.authority_source == "engineering_operator_decision":
            authority = self.records.get(
                "baseline-authorities", plan.plan_sha256, BaselineOperatorAuthorization
            )
            authority.validate_integrity()
            authority.require_plan_confirmation(plan)
            if (
                authority.authorization_sha256 != binding.authority_sha256
                or authority.plan_sha256 != plan.plan_sha256
                or authority.facts_sha256 != plan.facts.facts_sha256
                or authority.task_id != binding.task_id
                or authority.task_intent_sha256 != binding.task_intent_sha256
                or authority.continuation_mode != binding.continuation_mode
            ):
                raise ValueError("工程绑定没有对应的精确人工代码和规范确认")
        elif (
            binding.continuation_mode is not BaselineContinuationMode.RESUME
            or plan.facts.native_rule_change is not None
        ):
            raise ValueError("原工程策略不能批准暂停方式或变化的项目规范")
        else:
            admission = self.records.get(
                "baseline-authorities", plan.plan_sha256, EngineeringAdmission
            )
            EngineeringAuthority.validate(task=plan.facts.task, record=admission)
            if (
                admission.admission_sha256 != binding.authority_sha256
                or admission.plan_sha256 != plan.plan_sha256
                or admission.facts_sha256 != plan.facts.facts_sha256
                or admission.capabilities != (EngineeringCapability.EXECUTION_BASELINE_REBIND,)
            ):
                raise ValueError("工程绑定没有对应的精确组织工程批准")
        change = plan.facts.native_rule_change
        expected_epoch = (
            change.target.epoch_sha256
            if change is not None
            else previous.native_rule_epoch_sha256
            if previous is not None
            else None
        )
        if binding.native_rule_epoch_sha256 != expected_epoch:
            raise ValueError("工程绑定遗漏或替换了精确获批的完整项目规范版本")
        if expected_epoch is not None:
            epoch = self.native_rule_epoch(expected_epoch)
            if (epoch.scope, epoch.task_id) != (binding.scope, binding.task_id):
                raise ValueError("完整项目规范版本不属于当前需求和仓库")
            if change is not None:
                change.require_epoch(epoch)
                if (epoch.source_revision, epoch.target_base_ref) != (
                    binding.prior_execution_base_ref,
                    binding.execution_base_ref,
                ):
                    raise ValueError("规范批准与当前代码执行基线不同")

    def _require_rescue_binding(
        self, binding: ExecutionBaselineBinding, plan: ExecutionBaselinePlan
    ) -> None:
        if binding.purpose != plan.purpose:
            raise ValueError("工程绑定与批准方案的处置目的不同")
        if binding.purpose is not BaselinePurpose.LEGACY_WORKSPACE_RESCUE:
            if binding.legacy_containment_sha256 is not None:
                raise ValueError("普通基线绑定不能冒充旧执行救援")
            return
        containment = plan.facts.legacy_containment
        if (
            containment is None
            or binding.legacy_containment_sha256 != containment.containment_sha256
        ):
            raise ValueError("旧执行救援缺少完整的原执行和新隔离证据")
        containment.validate_integrity()
        authority = self.records.get(
            "baseline-authorities", plan.plan_sha256, BaselineOperatorAuthorization
        )
        authority.validate_integrity()
        authority.require_plan_confirmation(plan)
        if (
            authority.authorization_sha256 != binding.authority_sha256
            or authority.plan_sha256 != plan.plan_sha256
            or authority.facts_sha256 != plan.facts.facts_sha256
            or authority.task_id != binding.task_id
            or authority.task_intent_sha256 != binding.task_intent_sha256
            or binding.authority_source != "engineering_operator_decision"
        ):
            raise ValueError("旧执行救援没有对应的精确人工工程确认")

    def required_context(self, binding: ExecutionBaselineBinding) -> str:
        binding.validate_integrity()
        plan = self.plan(binding.plan_sha256)
        patch = plan.complete_capture.patch
        body = patch.encode("utf-8")
        if (
            binding.retained_patch.uri != self.patch_uri(plan.plan_sha256)
            or binding.retained_patch.sha256 != hashlib.sha256(body).hexdigest()
            or binding.retained_patch.bytes != len(body)
            or binding.task_id != plan.facts.task.id
            or binding.input_mode != plan.input_mode
            or binding.purpose != plan.purpose
        ):
            raise ValueError("complete retained baseline patch body changed")
        return (
            (
                "平台按人工工程决定保留了完整当前草稿, 代码基线和需求分支保持。"
                "原调用结果仍是未知; 这些草稿是新执行的工程输入, 不是原调用进度或候选通过证明。\n"
                if binding.purpose is BaselinePurpose.LEGACY_WORKSPACE_RESCUE
                else (
                    "平台已按精确工程授权在同一需求分支更新代码执行基线。"
                    "原需求范围与验收保持有效。\n"
                )
            )
            + f"原批准基线: {binding.approved_base_ref}\n新执行基线: {binding.execution_base_ref}\n"
            f"执行输入: {binding.execution_source_revision}\n模式: {binding.input_mode.value}\n"
            "以下是原执行基线到原候选和草稿的完整已封存补丁; "
            "必须完整阅读并适配, 不能把它当作通过的候选或验收。\n"
            f"完整旧补丁:\n{patch}"
        )
