"""Exact, bounded native Mock UI intent; never an ambient model GUI permission."""

from __future__ import annotations

import hashlib
import json
import os
import signal
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Annotated, Literal, Self

from pydantic import Field, StringConstraints, model_validator

from ai_software_engineer.agents.execution import ExecutionGuard
from ai_software_engineer.domain.model import DomainModel, NonEmptyStr
from ai_software_engineer.domain.visual_evidence import PngEvidence
from ai_software_engineer.manager.verification_environment import (
    SwiftSandboxCapability,
    discover_swift_sandbox_capability,
    swift_sandbox_command,
)


class NativeUiStep(DomainModel):
    name: Annotated[str, StringConstraints(min_length=1, max_length=100)]
    action: Literal["snapshot", "press", "scroll"] = "snapshot"
    role: Literal["AXButton", "AXCheckBox", "AXLink"] | None = None
    attribute: Literal["AXTitle", "AXDescription", "AXIdentifier"] | None = None
    value: Annotated[str, StringConstraints(min_length=1, max_length=200)] | None = None
    index: int = Field(default=0, ge=0, le=20)
    capture_window: Literal[True] | None = None
    scroll_position: float | None = Field(default=None, ge=0, le=1, allow_inf_nan=False)

    @model_validator(mode="after")
    def explicit_target(self) -> Self:
        fields = (self.role, self.attribute, self.value)
        if (self.action == "scroll") != (self.scroll_position is not None):
            raise ValueError("scroll requires a normalized position, other actions forbid it")
        if self.capture_window and self.action != "snapshot":
            raise ValueError("window capture requires a separately approved snapshot")
        if self.action == "press" and any(value is None for value in fields):
            raise ValueError("press requires an exact role and attribute selector")
        if self.role == "AXLink" and (self.attribute != "AXIdentifier" or self.index != 0):
            raise ValueError("link press requires one exact identifier")
        if self.action != "press" and (any(value is not None for value in fields) or self.index):
            raise ValueError("snapshot/scroll has no action target")
        return self


class NativeUiScenario(DomainModel):
    product: Annotated[str, StringConstraints(pattern=r"^[A-Za-z][A-Za-z0-9_-]{0,79}$")]
    mock_argument: Annotated[str, StringConstraints(pattern=r"^--mock-[a-z][a-z0-9-]{0,70}$")]
    window_title: Annotated[str, StringConstraints(min_length=1, max_length=200)]
    steps: Annotated[tuple[NativeUiStep, ...], Field(min_length=1, max_length=40)]

    @model_validator(mode="after")
    def snapshot_first(self) -> Self:
        if self.steps[0].action != "snapshot":
            raise ValueError("UI sequence must inspect the isolated window before interaction")
        if sum(step.capture_window is True for step in self.steps) > 6:
            raise ValueError("at most six window captures per scenario")
        return self


class NativeUiCapability(DomainModel):
    kind: Literal["macos_mock_ax_v1"] = "macos_mock_ax_v1"
    driver_sha256: Annotated[str, StringConstraints(pattern=r"^[a-f0-9]{64}$")]
    policy_sha256: Annotated[str, StringConstraints(pattern=r"^[a-f0-9]{64}$")]
    denied_user_root: NonEmptyStr
    scenario: NativeUiScenario


class NativeUiNode(DomainModel):
    path: str
    attributes: dict[str, str]


class NativeUiDiagnostics(DomainModel):
    session_status: Literal["READY", "SESSION_LOCKED", "SESSION_UNAVAILABLE"] | None = None
    ax_trusted: bool | None = None
    native_window_count: int | None = Field(default=None, ge=0)
    ax_status: int | None = None
    ax_window_count: int | None = Field(default=None, ge=0)
    launch_argv: tuple[str, str] | None = None
    process_running: bool | None = None
    process_returncode: int | None = None


class NativeUiCapture(DomainModel):
    window_id: int = Field(gt=0)
    image: PngEvidence


class NativeUiOutput(DomainModel):
    pid: int = Field(gt=1)
    action: Literal["snapshot", "press", "scroll"]
    nodes: Annotated[tuple[NativeUiNode, ...], Field(max_length=1000)]
    error: str | None = None
    diagnostic: str | None = None
    diagnostics: NativeUiDiagnostics | None = None
    capture: NativeUiCapture | None = None

    @model_validator(mode="after")
    def actual_window_evidence(self) -> Self:
        if self.error is None and (
            not self.nodes or self.nodes[0].attributes.get("AXRole") != "AXWindow"
        ):
            raise ValueError("successful UI evidence must start with an actual window")
        if any(
            n.attributes.get("AXRole") in {"AXApplication", "AXMenuBar", "AXMenu"}
            for n in self.nodes
        ):
            raise ValueError("UI evidence cannot include application roots or menus")
        return self


class NativeUiResult(DomainModel):
    step: NativeUiStep
    output: NativeUiOutput

    @model_validator(mode="after")
    def approved_capture(self) -> Self:
        expected = self.step.capture_window is True and self.output.error is None
        if (self.output.capture is not None) != expected:
            raise ValueError("window pixels must match the approved successful snapshot")
        return self


class NativeUiUnavailable(RuntimeError):
    """Fail closed without turning execution unavailability into an acceptance verdict."""


class NativeUiSessionUnavailable(NativeUiUnavailable):
    def __init__(self, code: Literal["SESSION_LOCKED", "SESSION_UNAVAILABLE"]) -> None:
        super().__init__(code)
        self.code = code


class NativeUiSession(DomainModel):
    status: Literal["READY", "SESSION_LOCKED", "SESSION_UNAVAILABLE"]


class NativeUiSessionPrerequisite(DomainModel):
    """Historical desktop failure plus a fresh observation, never an execution grant."""

    kind: Literal["macos_console_session"] = "macos_console_session"
    observed_status: Literal["SESSION_LOCKED", "SESSION_UNAVAILABLE"]
    current_session: NativeUiSession | None = None
    owner: Literal["logged_in_user"] = "logged_in_user"
    is_execution_mutex: Literal[False] = False

    @property
    def ready(self) -> bool:
        return self.current_session is not None and self.current_session.status == "READY"

    @property
    def next_action(self) -> str:
        if self.ready:
            return (
                "当前只读探测显示桌面会话可用; Manager 可重新提出精确验证计划, "
                "经独立人工审批后执行, 旧计划不能重放。这不是 UI 验收通过。"
            )
        unknown = "当前会话探测未成功, 不能确认已恢复。" if self.current_session is None else ""
        return (
            f"{unknown}责任方: 这台 Mac 的登录用户。请解锁运行 ASE 的 Mac 并保持登录桌面可用, "
            "然后通过正常“继续交付”让 Manager 重新检测; 无需提供密码。"
            "这是桌面会话前提, 不是执行互斥锁或队列租约, 不需要清理锁或终止其他执行。"
            "检测可用后由 Manager 重提精确计划并单独审批; 旧计划不能重放, 未产生验收结论。"
        )


def driver_source() -> Path:
    return Path(__file__).with_name("native_ui_driver.swift")


def native_ui_capability(scenario: NativeUiScenario) -> NativeUiCapability:
    return NativeUiCapability(
        driver_sha256=hashlib.sha256(driver_source().read_bytes()).hexdigest(),
        policy_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        denied_user_root=str(Path.home().resolve()),
        scenario=scenario,
    )


def native_ui_profile(capability: NativeUiCapability, binary: Path, scratch: Path) -> str:
    """Candidate process is read-only/no-network; only its private scratch is writable.

    AX needs GUI Mach services disallowed by the build sandbox. This is a distinct,
    explicitly approved Seatbelt capability, not a replacement for build isolation.
    """
    for path in (binary, scratch):
        if not path.is_absolute() or path.resolve(strict=True) != path:
            raise ValueError("native UI paths must be canonical")
    if not binary.is_relative_to(scratch) or not binary.is_file() or not scratch.is_dir():
        raise ValueError("native UI may launch only the private scratch build product")
    quote = json.dumps
    return "".join(
        (
            "(version 1)(allow default)",
            "(deny network*)(deny file-write*)",
            f"(allow file-write* (subpath {quote(str(scratch))}))",
            '(deny file-read-data (subpath "/Users") (subpath "/Volumes")',
            '(subpath "/private/var/root"))',
            f"(deny file-read-data (subpath {quote(capability.denied_user_root)}))",
            '(deny file-read-data (subpath "/private/var/folders"))',
            '(deny file-read-data (subpath "/private/tmp") (subpath "/tmp"))',
            '(deny file-read-data (subpath "/Library/Keychains"))',
            f"(allow file-read-data (subpath {quote(str(scratch))}))",
            "(deny process-exec)",
            f"(allow process-exec (literal {quote(str(binary))}))",
            "(deny appleevent-send)",
            '(deny mach-lookup (global-name "com.apple.securityd")',
            '(global-name "com.apple.coreservices.appleevents"))',
        )
    )


def _build_driver(
    build_capability: SwiftSandboxCapability,
    source: Path,
    scratch: Path,
    environment: dict[str, str],
) -> Path:
    driver = scratch / "ASEAXDriver"
    build = swift_sandbox_command(build_capability, source, scratch, "build")
    driver_command = (
        *build[: build.index("--") + 1],
        "/usr/bin/xcrun",
        "swiftc",
        str(driver_source()),
        "-module-cache-path",
        str(scratch / "clang"),
        "-o",
        str(driver),
    )
    compiled = subprocess.run(
        driver_command,
        cwd=source,
        env=environment,
        capture_output=True,
        timeout=60,
        check=False,
    )
    if compiled.returncode != 0 or not driver.is_file():
        raise NativeUiUnavailable("trusted native UI driver build failed")
    return driver


def _read_session(driver: Path, scratch: Path, environment: dict[str, str]) -> NativeUiSession:
    session_check = subprocess.run(
        [str(driver), "--session-check"],
        cwd=scratch,
        env=environment,
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    if session_check.returncode or len(session_check.stdout) > 1000:
        raise NativeUiUnavailable("invalid session preflight")
    try:
        return NativeUiSession.model_validate_json(session_check.stdout)
    except ValueError as error:
        raise NativeUiUnavailable("invalid session preflight") from error


def probe_native_ui_session(capability: SwiftSandboxCapability | None) -> NativeUiSession | None:
    """Read host readiness only. Never build/launch a candidate or traverse its AX tree."""
    if capability is None:
        return None
    try:
        if discover_swift_sandbox_capability(capability.sandbox_executable) != capability:
            return None
        with tempfile.TemporaryDirectory(prefix="ase-session-probe-") as temporary:
            scratch = Path(temporary).resolve(strict=True)
            for name in ("tmp", "clang"):
                (scratch / name).mkdir(mode=0o700)
            environment = {
                "PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
                "LANG": "C",
                "LC_ALL": "C",
                "DEVELOPER_DIR": capability.developer_directory,
                "TMPDIR": str(scratch / "tmp"),
                "CLANG_MODULE_CACHE_PATH": str(scratch / "clang"),
            }
            driver = _build_driver(
                capability, driver_source().parent.resolve(), scratch, environment
            )
            return _read_session(driver, scratch, environment)
    except (NativeUiUnavailable, OSError, ValueError, subprocess.SubprocessError):
        return None


def run_native_ui(
    capability: NativeUiCapability,
    build_capability: SwiftSandboxCapability,
    source: Path,
    scratch: Path,
    environment: dict[str, str],
    guard: ExecutionGuard | None = None,
) -> tuple[NativeUiResult, ...]:
    """Build the trusted driver in the build sandbox; inspect only our mock child window.

    Call only after the containing exact plan's role admission and durable STARTED receipt.
    No model-selected executable, arbitrary shell, global AX tree or user app attachment exists.
    """
    if capability != native_ui_capability(capability.scenario):
        raise NativeUiUnavailable("UI capability changed; a fresh exact plan is required")
    binary_link = scratch / "build" / "debug" / capability.scenario.product
    try:
        binary = binary_link.resolve(strict=True)
        profile = native_ui_profile(capability, binary, scratch)
    except (OSError, ValueError) as error:
        raise NativeUiUnavailable("approved UI product is unavailable") from error
    if guard is not None:
        guard.check()
    driver = _build_driver(build_capability, source, scratch, environment)
    session = _read_session(driver, scratch, environment)
    if session.status != "READY":
        raise NativeUiSessionUnavailable(session.status)
    if guard is not None:
        guard.check()
    results: list[NativeUiResult] = []
    evidence_bytes = 0
    launch_argv = (str(binary), capability.scenario.mock_argument)
    # GUI process output is discarded, never a model instruction/evidence injection channel.
    with subprocess.Popen(
        ["/usr/bin/sandbox-exec", "-p", profile, *launch_argv],
        cwd=scratch,
        env=environment,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    ) as process:
        try:
            # Let AppKit register its window/AX server before the first attachment attempt.
            time.sleep(2)
            for index, step in enumerate(capability.scenario.steps):
                deadline = time.monotonic() + (15 if index == 0 else 3)
                while True:
                    if guard is not None:
                        guard.check()
                    returncode = process.poll()
                    if returncode is not None:
                        results.append(
                            NativeUiResult(
                                step=step,
                                output=NativeUiOutput(
                                    pid=process.pid,
                                    action=step.action,
                                    nodes=(),
                                    error="PROCESS_EXITED",
                                    diagnostics=NativeUiDiagnostics(
                                        launch_argv=launch_argv,
                                        process_running=False,
                                        process_returncode=returncode,
                                    ),
                                ),
                            )
                        )
                        return tuple(results)
                    response = subprocess.run(
                        [str(driver)],
                        input=json.dumps(
                            {
                                "pid": process.pid,
                                "window_title": capability.scenario.window_title,
                                "step": step.to_wire(),
                            }
                        ),
                        cwd=scratch,
                        env=environment,
                        capture_output=True,
                        text=True,
                        timeout=20,
                        check=False,
                    )
                    if len(response.stdout) > 2_000_000:
                        raise NativeUiUnavailable("native UI evidence exceeded the bound")
                    try:
                        output = NativeUiOutput.model_validate_json(response.stdout)
                    except ValueError as error:
                        raise NativeUiUnavailable(
                            "native UI driver returned invalid evidence"
                        ) from error
                    if output.pid != process.pid or output.action != step.action:
                        raise NativeUiUnavailable("native UI result does not belong to this action")
                    returncode = process.poll()
                    output = output.model_copy(
                        update={
                            "diagnostics": (output.diagnostics or NativeUiDiagnostics()).model_copy(
                                update={
                                    "launch_argv": launch_argv,
                                    "process_running": returncode is None,
                                    "process_returncode": returncode,
                                },
                            ),
                        }
                    )
                    # A press is never retried: an uncertain side effect must not be replayed.
                    if (
                        step.action == "snapshot"
                        and output.error == "WINDOW_UNAVAILABLE"
                        and time.monotonic() < deadline
                    ):
                        time.sleep(0.2)
                        continue
                    try:
                        results.append(NativeUiResult(step=step, output=output))
                    except ValueError as error:
                        raise NativeUiUnavailable(
                            "native UI evidence does not match the approved snapshot"
                        ) from error
                    evidence_bytes += len(response.stdout.encode("utf-8"))
                    if evidence_bytes > 4_000_000:
                        raise NativeUiUnavailable("native UI evidence exceeded the sequence bound")
                    break
                if output.error is not None:
                    break
        finally:
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGTERM)
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait(timeout=5)
    return tuple(results)
