#!/usr/bin/env python3
"""Local controlled fault retirement and explicit maintenance completion."""

from __future__ import annotations

import argparse
import os
import sys

from ai_software_engineer.config.production import ProductionConfig
from ai_software_engineer.config.runtime_environment import (
    LocalRuntimeEnvironmentStore,
    runtime_environment_path,
)
from ai_software_engineer.web_console.fault_log_retention import purge_archived_log
from ai_software_engineer.web_console.fault_retirement import (
    execute_fault_retirement,
    prepare_fault_retirement,
    verify_retired_log,
)
from ai_software_engineer.web_console.maintenance_completion import (
    complete_maintenance,
    prepare_maintenance_completion,
)
from ai_software_engineer.web_console.service_lifecycle import ServiceLifecycleError


def main() -> int:
    parser = argparse.ArgumentParser(
        description="核验故障服务归档与维护完成方案; 恢复普通服务不会继续需求。"
    )
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("prepare")
    execute = commands.add_parser("execute")
    execute.add_argument("--plan", required=True)
    execute.add_argument("--confirm-fault-retirement", action="store_true")
    commands.add_parser("verify-archived-log")
    purge = commands.add_parser("purge-archived-log")
    purge.add_argument("--confirm-delete-archived-log", action="store_true")
    commands.add_parser("prepare-completion")
    complete = commands.add_parser("complete")
    complete.add_argument("--plan", required=True)
    complete.add_argument("--confirm-restore-normal", action="store_true")
    args = parser.parse_args()
    try:
        if args.command == "prepare":
            print(prepare_fault_retirement(os.environ).model_dump_json())
        elif args.command == "execute":
            print(
                execute_fault_retirement(
                    os.environ,
                    plan_sha256=args.plan,
                    confirm_fault_retirement=args.confirm_fault_retirement,
                ).model_dump_json()
            )
        elif args.command == "verify-archived-log":
            print(verify_retired_log(os.environ).model_dump_json())
        elif args.command == "purge-archived-log":
            print(
                purge_archived_log(
                    os.environ,
                    confirm_delete_archived_log=args.confirm_delete_archived_log,
                ).model_dump_json()
            )
        else:
            environment = dict(os.environ)
            source = ProductionConfig.path_from_environment(environment)
            config = ProductionConfig.from_file(source)
            stored = LocalRuntimeEnvironmentStore(runtime_environment_path(source)).load()
            # Only the configured database credential is needed for read-only checking.
            name = config.database.dsn_env
            if name in stored:
                environment[name] = stored[name]
            if args.command == "prepare-completion":
                print(prepare_maintenance_completion(environment).model_dump_json())
            else:
                print(
                    complete_maintenance(
                        environment,
                        plan_sha256=args.plan,
                        confirm_restore_normal=args.confirm_restore_normal,
                    ).model_dump_json()
                )
    except (OSError, ValueError, RuntimeError) as error:
        print(
            str(error)
            if isinstance(error, ServiceLifecycleError)
            else "服务维护无法核验, 原记录与现场保留; 未启动服务。",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
