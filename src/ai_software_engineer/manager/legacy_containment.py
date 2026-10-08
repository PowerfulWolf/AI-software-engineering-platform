"""New local boot facts contain a legacy invocation; they never rewrite its outcome."""

from __future__ import annotations

import hashlib
import os
import re
import stat
import subprocess
import sys
import tempfile
import uuid
from datetime import UTC, datetime
from typing import Literal, Protocol, Self

from pydantic import AwareDatetime, Field, model_validator

from ai_software_engineer.domain.artifact import Sha256
from ai_software_engineer.domain.engineering_authority import EngineeringScope
from ai_software_engineer.domain.enums import AgentRole
from ai_software_engineer.domain.model import DomainModel, NonEmptyStr
from ai_software_engineer.manager.legacy_local_execution import LegacyLocalExecutionSurvey
from ai_software_engineer.recovery.models import digest
from ai_software_engineer.work_queue.invocation import DeliveryInvocationStart
from ai_software_engineer.work_queue.models import QueueClaim

_MAX_OS_BYTES = 65_536
_PREREQUISITE = (
    "尚不能确认旧执行已被隔离。请在保存其他工作后重启原执行所在的整台电脑, "
    "启动 ASE 后重新检查; 仅重启 ASE 服务不能满足这个条件。"
)


class LocalBootObservation(DomainModel):
    """Stable boot identity, with raw device identifiers never stored or displayed."""

    machine_sha256: Sha256
    boot_session_sha256: Sha256
    booted_at: AwareDatetime

    def same_boot(self, other: LocalBootObservation) -> bool:
        return self == other


class LocalBootObserver(Protocol):
    def observe(self) -> LocalBootObservation: ...


class TrustedLocalBootObserver:
    """Fixed read-only OS queries; request inputs cannot select commands or paths."""

    def _command(self, argv: tuple[str, ...]) -> str:
        # OS query output goes to an isolated temporary file, not an unbounded
        # PIPE buffer. Only a bounded body is read; identifiers never enter errors.
        with tempfile.TemporaryFile() as output:
            try:
                result = subprocess.run(
                    argv,
                    stdin=subprocess.DEVNULL,
                    stdout=output,
                    stderr=subprocess.DEVNULL,
                    cwd="/",
                    env={"PATH": "/usr/bin:/bin:/usr/sbin:/sbin", "LANG": "C"},
                    timeout=3,
                    check=False,
                    shell=False,
                )
                if result.returncode or output.tell() > _MAX_OS_BYTES:
                    raise ValueError(_PREREQUISITE)
                output.seek(0)
                return output.read(_MAX_OS_BYTES + 1).decode("utf-8", errors="strict").strip()
            except (OSError, subprocess.SubprocessError, UnicodeError) as error:
                raise ValueError(_PREREQUISITE) from error

    def _file(self, path: str) -> str:
        try:
            descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
            with os.fdopen(descriptor, "rb") as source:
                if not stat.S_ISREG(os.fstat(source.fileno()).st_mode):
                    raise ValueError(_PREREQUISITE)
                body = source.read(_MAX_OS_BYTES + 1)
            if len(body) > _MAX_OS_BYTES:
                raise ValueError(_PREREQUISITE)
            return body.decode("ascii", errors="strict").strip()
        except (OSError, UnicodeError) as error:
            raise ValueError(_PREREQUISITE) from error

    def observe(self) -> LocalBootObservation:
        try:
            if sys.platform == "darwin":
                session = str(
                    uuid.UUID(self._command(("/usr/sbin/sysctl", "-n", "kern.bootsessionuuid")))
                )
                boot = self._command(("/usr/sbin/sysctl", "-n", "kern.boottime"))
                match = re.search(r"\bsec\s*=\s*(\d+)\s*,", boot)
                machine_body = self._command(
                    ("/usr/sbin/ioreg", "-r", "-d", "1", "-c", "IOPlatformExpertDevice")
                )
                identities = re.findall(r'"IOPlatformUUID"\s*=\s*"([^"]+)"', machine_body)
                if match is None or len(identities) != 1:
                    raise ValueError(_PREREQUISITE)
                machine = str(uuid.UUID(identities[0]))
                booted_at = datetime.fromtimestamp(int(match[1]), UTC)
            elif sys.platform.startswith("linux"):
                machine = self._file("/etc/machine-id")
                if not re.fullmatch(r"[a-fA-F0-9]{32}", machine):
                    raise ValueError(_PREREQUISITE)
                session = str(uuid.UUID(self._file("/proc/sys/kernel/random/boot_id")))
                matches = re.findall(r"^btime (\d+)$", self._file("/proc/stat"), flags=re.MULTILINE)
                if len(matches) != 1:
                    raise ValueError(_PREREQUISITE)
                booted_at = datetime.fromtimestamp(int(matches[0]), UTC)
                machine = machine.lower()
            else:
                raise ValueError(_PREREQUISITE)
            if booted_at > datetime.now(UTC):
                raise ValueError(_PREREQUISITE)
            return LocalBootObservation(
                machine_sha256=hashlib.sha256(machine.encode("ascii")).hexdigest(),
                boot_session_sha256=hashlib.sha256(session.encode("ascii")).hexdigest(),
                booted_at=booted_at,
            )
        except (ValueError, OverflowError) as error:
            raise ValueError(_PREREQUISITE) from error


class LegacyExecutionContainment(DomainModel):
    """Exact new engineering facts, separate from an original process-stop receipt."""

    kind: Literal["legacy_execution_containment_v1"] = "legacy_execution_containment_v1"
    scope: EngineeringScope
    requirement_id: NonEmptyStr
    dispatch_sha256: Sha256
    task_intent_sha256: Sha256
    original_start: DeliveryInvocationStart
    original_claim: QueueClaim
    boot: LocalBootObservation
    method: Literal["os_reboot", "operator_confirmed_local_stop"] = Field(
        default="os_reboot", exclude_if=lambda value: value == "os_reboot"
    )
    local_execution_survey: LegacyLocalExecutionSurvey | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    containment_sha256: Sha256

    @model_validator(mode="after")
    def validate_binding(self) -> Self:
        start, claim = self.original_start, self.original_claim
        request, item = start.request, claim.work_item
        start.validate_integrity()
        QueueClaim.model_validate(claim.to_wire())
        if (
            request.role is not AgentRole.CODER
            or claim.model_selection.route_kind != "codex_cli"
            or claim.claimed_at > start.started_at
            or self.scope.repository_root not in item.repository_scopes
            or (
                start.work_item_id,
                start.lease_id,
                start.checkpoint_sequence,
                request.task_id,
                request.role,
                request.attempt,
                self.scope.repository_id,
            )
            != (
                item.id,
                claim.lease.id,
                item.checkpoint_sequence,
                item.task_id,
                item.role,
                item.attempt,
                item.repository_id,
            )
        ):
            raise ValueError("旧执行救援缺少精确本机 Coder 调用和真实历史领取记录")
        if self.method == "os_reboot":
            if self.local_execution_survey is not None:
                raise ValueError("整机重启隔离记录不能混入本机人工停止调查")
            if self.boot.booted_at <= start.started_at:
                raise ValueError(_PREREQUISITE)
        else:
            survey = self.local_execution_survey
            if survey is None:
                raise ValueError("本机人工停止路径必须有完整的本机执行调查")
            survey.require_idle()
            if (
                survey.machine_sha256 != self.boot.machine_sha256
                or survey.boot_session_sha256 != self.boot.boot_session_sha256
                or survey.observed_at < start.started_at
            ):
                raise ValueError("本机执行调查与原调用和当前机器边界不一致")
        return self

    def validate_integrity(self) -> None:
        type(self).model_validate(self.to_wire())
        if self.containment_sha256 != digest(
            self.model_dump(mode="json", exclude={"containment_sha256"})
        ):
            raise ValueError("旧执行隔离观察记录完整性异常")

    @classmethod
    def create(cls, **values: object) -> Self:
        value = cls.model_validate({**values, "containment_sha256": "0" * 64})
        return value.model_copy(
            update={
                "containment_sha256": digest(
                    value.model_dump(mode="json", exclude={"containment_sha256"})
                )
            }
        )
