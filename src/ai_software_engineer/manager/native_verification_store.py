"""Immutable normal-role verification records in the registered repository sidecar."""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import TypeVar

from ai_software_engineer.domain.model import DomainModel
from ai_software_engineer.domain.native_verification import (
    NativeRoleVerificationAdmission,
    NativeRoleVerificationPlan,
)
from ai_software_engineer.manager.python_verification import PythonMysqlSandboxCapability
from ai_software_engineer.recovery.python_mysql_records import MysqlResourceRecord
from ai_software_engineer.recovery.store import RecoveryRecordMissing
from ai_software_engineer.recovery.verification_records import VerificationExecutionRecord

M = TypeVar("M", bound=DomainModel)


class NativeRoleVerificationBinding(DomainModel):
    plan: NativeRoleVerificationPlan
    admission: NativeRoleVerificationAdmission
    capability: PythonMysqlSandboxCapability

    def validate_integrity(self) -> None:
        from ai_software_engineer.domain.native_verification import role_verification_digest

        plan, admission = self.plan, self.admission
        plan.validate_integrity()
        admission.validate_integrity()
        if (
            (
                plan.task_id,
                plan.task_intent_sha256,
                plan.run_id,
                plan.role,
                plan.plan_sha256,
                plan.request_sha256,
                plan.policy_sha256,
                plan.work_attempt,
            )
            != (
                admission.task_id,
                admission.task_intent_sha256,
                admission.run_id,
                admission.role,
                admission.plan_sha256,
                admission.request_sha256,
                admission.policy_sha256,
                admission.work_attempt,
            )
            or admission.policy.scope != plan.scope
            or role_verification_digest(self.capability.to_wire()) != plan.capability_sha256
        ):
            raise ValueError("native role binding identity changed")


class NativeRoleVerificationStore:
    """One original Run's journal; no Task/verdict/recovery mutations exist here."""

    def __init__(self, root: Path, binding: NativeRoleVerificationBinding) -> None:
        binding.validate_integrity()
        root = root.absolute()
        repository = Path(binding.plan.scope.repository_root)
        if root.is_relative_to(repository) or any(
            path.is_symlink() for path in (root, *root.parents)
        ):
            raise ValueError("native verification records require an external canonical sidecar")
        root.mkdir(parents=True, mode=0o700, exist_ok=True)
        if root.resolve(strict=True) != root:
            raise ValueError("native verification sidecar root changed")
        self.root = root / hashlib.sha256(binding.plan.run_id.encode()).hexdigest()
        self.root.mkdir(mode=0o700, exist_ok=True)
        if self.root.resolve(strict=True) != self.root:
            raise ValueError("native verification Run directory changed")
        try:
            previous = self._get("binding", NativeRoleVerificationBinding)
        except RecoveryRecordMissing:
            previous = self._put("binding", binding, NativeRoleVerificationBinding)
        previous.validate_integrity()
        if (
            previous.plan.plan_sha256 != binding.plan.plan_sha256
            or previous.admission.admission_sha256 != binding.admission.admission_sha256
            or previous.capability != binding.capability
        ):
            raise ValueError("a normal role Run cannot acquire different verification authority")
        self.binding = previous

    @contextmanager
    def execution_lock(self) -> Iterator[None]:
        descriptor = os.open(
            self.root / "execution.lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600
        )
        try:
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as error:
                raise ValueError("normal role verification still has a live executor") from error
            yield
        finally:
            os.close(descriptor)

    def _get(self, name: str, model: type[M]) -> M:
        path = self.root / (name + ".json")
        try:
            descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        except FileNotFoundError as error:
            raise RecoveryRecordMissing("native verification record is missing") from error
        with os.fdopen(descriptor, "rb") as stream:
            content = stream.read(8_000_001)
        if len(content) > 8_000_000:
            raise ValueError("native verification record exceeds its bound")
        record = model.model_validate_json(content)
        return record

    def _put(self, name: str, record: M, model: type[M]) -> M:
        typed = model.model_validate(record.to_wire())
        try:
            previous = self._get(name, model)
        except RecoveryRecordMissing:
            pass
        else:
            if previous != typed:
                raise ValueError("immutable native verification record changed")
            return previous
        descriptor, temporary = tempfile.mkstemp(prefix=".record-", dir=self.root)
        path = self.root / (name + ".json")
        try:
            with os.fdopen(descriptor, "w") as stream:
                json.dump(
                    typed.to_wire(),
                    stream,
                    sort_keys=True,
                    ensure_ascii=False,
                    separators=(",", ":"),
                )
                stream.flush()
                os.fsync(stream.fileno())
            try:
                os.link(temporary, path)
            except FileExistsError:
                previous = self._get(name, model)
                if previous != typed:
                    raise ValueError("concurrent native verification record changed") from None
            return self._get(name, model)
        finally:
            os.unlink(temporary)

    def get_verification_execution(self, *, completed: bool) -> VerificationExecutionRecord:
        record = self._get("finished" if completed else "started", VerificationExecutionRecord)
        self._validate_execution(record)
        if (record.phase != "STARTED") != completed:
            raise ValueError("native verification execution phase changed")
        return record

    def _validate_execution(self, record: VerificationExecutionRecord) -> None:
        record.validate_integrity()
        plan, admission = self.binding.plan, self.binding.admission
        if (
            record.plan_sha256 != plan.plan_sha256
            or record.invocation_sha256 != plan.request_sha256
            or record.authorization_sha256 != admission.admission_sha256
            or record.candidate_revision != plan.candidate_revision
            or record.role is not plan.role
            or record.source_root != plan.workspace_root
            or record.capability != self.binding.capability
            or record.native_ui is not None
        ):
            raise ValueError("native verification execution does not bind original role authority")

    def put_verification_execution(
        self, record: VerificationExecutionRecord
    ) -> VerificationExecutionRecord:
        self._validate_execution(record)
        if record.phase != "STARTED":
            started = self.get_verification_execution(completed=False)
            if (
                started.model_dump(
                    exclude={"phase", "recorded_at", "record_sha256", "results", "failure_code"}
                )
                != record.model_dump(
                    exclude={"phase", "recorded_at", "record_sha256", "results", "failure_code"}
                )
                or record.recorded_at < started.recorded_at
            ):
                raise ValueError("native final execution differs from its durable start")
        return self._put(
            "started" if record.phase == "STARTED" else "finished",
            record,
            VerificationExecutionRecord,
        )

    def get_mysql_resource(self, resource_id: str, phase: str) -> MysqlResourceRecord:
        if len(resource_id) != 64 or any(value not in "abcdef0123456789" for value in resource_id):
            raise ValueError("invalid native verification resource identity")
        if phase not in {"INTENT", "CREATED", "CLEANED", "CLEANUP_FAILED"}:
            raise ValueError("invalid native verification resource phase")
        record = self._get("resource-" + resource_id + "-" + phase, MysqlResourceRecord)
        self._validate_resource(record)
        if record.intent.resource_id != resource_id or record.phase != phase:
            raise ValueError("native verification resource record changed")
        return record

    def _validate_resource(self, record: MysqlResourceRecord) -> None:
        record.validate_integrity()
        started = self.get_verification_execution(completed=False)
        if (
            record.intent.plan_sha256 != started.plan_sha256
            or record.intent.invocation_sha256 != started.invocation_sha256
            or record.intent.role != started.role.value
            or record.intent.capability != started.capability
            or record.intent.resource_id != started.mysql_resource_id
            or record.intent.recorded_at > started.recorded_at
        ):
            raise ValueError("native resource does not bind its admitted execution")

    def put_mysql_resource(self, record: MysqlResourceRecord) -> MysqlResourceRecord:
        self._validate_resource(record)
        if record.phase != "INTENT":
            intent = self.get_mysql_resource(record.intent.resource_id, "INTENT")
            if intent.intent != record.intent:
                raise ValueError("native resource intent changed")
            for phase in ("CREATED", "CLEANUP_FAILED"):
                try:
                    observed = self.get_mysql_resource(record.intent.resource_id, phase)
                except RecoveryRecordMissing:
                    continue
                if (
                    observed.container_id is not None
                    and record.container_id is not None
                    and observed.container_id != record.container_id
                ) or (
                    observed.configuration_sha256 is not None
                    and record.configuration_sha256 is not None
                    and observed.configuration_sha256 != record.configuration_sha256
                ):
                    raise ValueError("native resource ownership observation changed")
        return self._put(
            "resource-" + record.intent.resource_id + "-" + record.phase,
            record,
            MysqlResourceRecord,
        )

    def list_mysql_resource_intents(self) -> tuple[MysqlResourceRecord, ...]:
        names = sorted(path.name for path in self.root.glob("resource-*-INTENT.json"))
        if len(names) > 32:
            raise ValueError("native role resource inventory exceeds its bound")
        return tuple(
            self.get_mysql_resource(
                name.removeprefix("resource-").removesuffix("-INTENT.json"),
                "INTENT",
            )
            for name in names
        )
