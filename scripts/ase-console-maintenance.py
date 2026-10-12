#!/usr/bin/env python3
"""Local exact fault retirement: the successor is always inspection, never delivery."""

from __future__ import annotations

import argparse
import os
import sys

from ai_software_engineer.web_console.fault_retirement import (
    execute_fault_retirement,
    prepare_fault_retirement,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="将精确故障服务归档并替换为只读检查服务; 不会继续需求。"
    )
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("prepare")
    execute = commands.add_parser("execute")
    execute.add_argument("--plan", required=True)
    execute.add_argument("--confirm-fault-retirement", action="store_true")
    args = parser.parse_args()
    try:
        if args.command == "prepare":
            print(prepare_fault_retirement(os.environ).model_dump_json())
        else:
            print(
                execute_fault_retirement(
                    os.environ,
                    plan_sha256=args.plan,
                    confirm_fault_retirement=args.confirm_fault_retirement,
                ).model_dump_json()
            )
    except (OSError, ValueError, RuntimeError):
        print("故障服务维护无法核验, 原记录与现场保留; 未启动服务。", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
