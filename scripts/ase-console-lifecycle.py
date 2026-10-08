#!/usr/bin/env python3
"""Trusted local service-script handshake; never accepts shell text or arbitrary paths."""

from __future__ import annotations

import fcntl
import os
import stat
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

try:
    from ai_software_engineer.web_console.service_lifecycle import (
        ServiceLifecycleError,
        ServiceLifecycleStore,
        ServiceShutdownAction,
        ServiceShutdownRequest,
        ServiceState,
    )
except (ImportError, SyntaxError):
    print("受控重启组件无法加载, 未停止原服务; 请完成代码与依赖安装。", file=sys.stderr)
    raise SystemExit(1) from None


def alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


def locked(store: ServiceLifecycleStore, action: str, arguments: list[str]) -> None:
    if action not in {"start", "stop", "restart", "resume", "apply"}:
        raise ServiceLifecycleError("服务控制操作无效。")
    root = store.root
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    metadata = root.lstat()
    if (
        not stat.S_ISDIR(metadata.st_mode)
        or metadata.st_uid != os.getuid()
        or metadata.st_mode & 0o022
    ):
        raise ServiceLifecycleError("服务控制目录不可用。")
    descriptor = os.open(
        root / "console-service-replacement.lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600
    )
    metadata = os.fstat(descriptor)
    if (
        not stat.S_ISREG(metadata.st_mode)
        or metadata.st_uid != os.getuid()
        or stat.S_IMODE(metadata.st_mode) != 0o600
        or metadata.st_nlink != 1
    ):
        raise ServiceLifecycleError("服务控制锁不可用。")
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError as error:
        raise ServiceLifecycleError("已有服务控制操作正在执行, 请等待完成后再试。") from error
    os.set_inheritable(descriptor, True)
    os.environ["ASE_REPLACEMENT_LOCK_FD"] = str(descriptor)
    script = Path(__file__).resolve().with_name("ase-console-service.sh")
    os.execv(str(script), [str(script), "locked", action, *arguments])


def request(store: ServiceLifecycleStore, pid: int, action: str, timeout: float) -> str:
    instance = store.read_instance()
    if instance is None or instance.pid != pid or not alive(pid):
        raise ServiceLifecycleError(
            "当前服务没有可验证的受控关闭记录; 未发送停服信号, 也未启动替代服务。"
        )
    value = ServiceShutdownRequest.new(
        instance,
        at=datetime.now(UTC),
        timeout_seconds=timeout,
        action=ServiceShutdownAction(action),
    )
    store.write_request(value)
    return value.request_id


def wait(store: ServiceLifecycleStore, pid: int, request_id: str) -> None:
    value = store.read_request()
    if value is None or value.request_id != request_id or value.pid != pid:
        raise ServiceLifecycleError("受控关闭请求已变更; 未启动替代服务。")
    deadline = time.monotonic() + value.timeout_seconds + 5
    while time.monotonic() < deadline:
        current_request = store.read_request()
        instance = store.read_instance()
        if current_request != value or instance is None or not value.matches(instance):
            raise ServiceLifecycleError("服务或请求身份已变更; 未启动替代服务。")
        result = store.read_result()
        if result is not None and result.matches(value):
            if result.recorded_at < value.requested_at or instance.updated_at < value.requested_at:
                raise ServiceLifecycleError("安全收尾记录时间不匹配; 未启动替代服务。")
            if result.state == ServiceState.REFUSED:
                raise ServiceLifecycleError(result.safe_summary)
            if (
                value.action == ServiceShutdownAction.RESUME
                and result.state == ServiceState.RUNNING
                and instance.state == ServiceState.RUNNING
            ):
                print(result.safe_summary)
                return
            if (
                value.action == ServiceShutdownAction.SHUTDOWN
                and result.state == ServiceState.READY
                and instance.state == ServiceState.READY
            ):
                exit_deadline = time.monotonic() + 20
                while alive(pid) and time.monotonic() < exit_deadline:
                    time.sleep(0.05)
                if alive(pid):
                    raise ServiceLifecycleError("安全收尾已记录, 但服务尚未退出; 未启动替代服务。")
                print(result.safe_summary)
                return
        if not alive(pid):
            raise ServiceLifecycleError("服务已退出, 但缺少本次安全收尾证明; 未启动替代服务。")
        time.sleep(0.05)
    raise ServiceLifecycleError("未收到本次安全收尾证明; 保留原服务, 不强制停止或启动替代服务。")


def main() -> int:
    try:
        store = ServiceLifecycleStore.from_environment(os.environ)
        command = sys.argv[1]
        if command == "locked":
            locked(store, sys.argv[2], sys.argv[3:])
        elif command == "verify-lock":
            descriptor = int(os.environ.get("ASE_REPLACEMENT_LOCK_FD", "-1"))
            metadata = os.fstat(descriptor)
            expected = (store.root / "console-service-replacement.lock").lstat()
            if (
                not stat.S_ISREG(expected.st_mode)
                or (metadata.st_dev, metadata.st_ino) != (expected.st_dev, expected.st_ino)
                or metadata.st_uid != os.getuid()
                or stat.S_IMODE(metadata.st_mode) != 0o600
                or metadata.st_nlink != 1
            ):
                raise ServiceLifecycleError("缺少有效的服务控制锁。")
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        elif command == "request":
            print(request(store, int(sys.argv[2]), sys.argv[3], float(sys.argv[4])))
        elif command == "wait":
            wait(store, int(sys.argv[2]), sys.argv[3])
        elif command == "dead":
            instance = store.read_instance()
            result = store.read_result()
            value = store.read_request()
            if (
                instance is None
                or instance.pid != int(sys.argv[2])
                or instance.state != ServiceState.READY
                or result is None
                or value is None
                or not value.matches(instance)
                or not result.matches(value)
                or result.state != ServiceState.READY
                or result.recorded_at < value.requested_at
                or instance.updated_at < value.requested_at
            ):
                raise ServiceLifecycleError(
                    "旧服务未留下安全收尾证明; 请先核对原执行, 不能直接替换。"
                )
        elif command == "initial":
            instance = store.read_instance()
            if instance is not None:
                if alive(instance.pid):
                    raise ServiceLifecycleError("旧服务仍在运行, 但缺少 PID 记录; 未启动替代服务。")
                result = store.read_result()
                value = store.read_request()
                if (
                    instance.state != ServiceState.READY
                    or result is None
                    or value is None
                    or not value.matches(instance)
                    or not result.matches(value)
                    or result.state != ServiceState.READY
                    or result.recorded_at < value.requested_at
                    or instance.updated_at < value.requested_at
                ):
                    raise ServiceLifecycleError(
                        "旧服务未留下安全收尾证明; 请先核对原执行, 不能直接替换。"
                    )
        elif command == "status":
            instance = store.read_instance()
            if instance is None or instance.pid != int(sys.argv[2]):
                print("当前服务尚不支持受控重启。")
            else:
                print(instance.safe_summary)
        elif command == "instance-id":
            instance = store.read_instance()
            print(instance.instance_id if instance is not None else "")
        elif command == "started":
            pid, previous_id = int(sys.argv[2]), sys.argv[3]
            deadline = time.monotonic() + 5
            while alive(pid) and time.monotonic() < deadline:
                instance = store.read_instance()
                if (
                    instance is not None
                    and instance.pid == pid
                    and instance.instance_id != previous_id
                    and instance.state == ServiceState.RUNNING
                ):
                    return 0
                time.sleep(0.05)
            raise ServiceLifecycleError("新服务尚未建立受控生命周期记录; 请查看服务状态。")
        else:
            raise ServiceLifecycleError("服务控制操作无效。")
    except (ServiceLifecycleError, OSError, ValueError, IndexError):
        # Exception text may contain paths or untrusted content. Only our fixed
        # domain summaries are exposed; filesystem/parser errors stay generic.
        error = sys.exc_info()[1]
        summary = str(error) if isinstance(error, ServiceLifecycleError) else "服务控制记录不可用。"
        print(summary, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
