# 实现里程碑与质量门

## 本次实现

1. **完成实际故障归因与可信启动契约。** 既有调查显示 Darwin 的真实 setuid `/bin/ps` 活着时无法由普通账户读取出生身份；实际进程退出成功不补足已丢失的初始 capture。PRD/design 明确规定必须在目标执行前 capture，不能修改 owned-session 判停或把 EPERM 当 absence。
2. **落实固定可信启动门。** `owned_spawn.spawn_owned_query` 用真实 isolated Popen 启动版本固定的 Python `-I -S -B` bootstrap；父进程执行原 capture/二次 observation 后，才以有界私有 ACK/env 帧放行相同 PID 的目标 exec。原 token argv、显式环境、stdio 和 cwd 精确保留；两端关闭控制 FD。
3. **接入仅有两个可信 caller。** `TrustedLegacyLocalExecutionObserver._query` 与 `bounded_verification_command` 使用同一实际 Popen/observation。原 caller 输出、超时、停止和 EOF 判据继续生效；没有 Agent 工具、native Coder 启动或角色权限变化。
4. **真实失败路径与边界验证。** capture、二次 observation 或 ACK 失败不执行目标；只清理父进程持有的实际 bootstrap。UNKNOWN 保留，不被 cleanup 成功抹去。setuid 目标在活着/超时阶段不可核验仍拒绝。测试覆盖真实 PID/SID 保持、短命查询、FD、完整环境及逃逸输出管道。
5. **修复增量回归发现的独立 inventory 缺口。** clean main `88128c3` 同样存在 `d4d6f32` 增加第 11 图之后测试/同步脚本仍要求 10 图的问题。Root 扩展范围后，以独立精确名称集合修复测试及生成器，保留逐图与 handwritten guard；缺图、多图、同数量替换图在任何写入前拒绝。没有改实际发布 Schema bytes。
6. **同步组织知识与存量说明。** `owned-session-stop.md` 记录 bootstrap/ACK、原 stop 判据、setuid failure mode、精确 inventory 与历史 UNKNOWN 不回填规则；详细命令、结果、限制、存量和回滚见 `validation.md`。

## 已执行质量门

| 门 | 实际证据 |
|---|---|
| 真实 Darwin 启动门正反与边界 | 24 场景通过；原 18 场景 4.15s，扩充后在两文件复验中全部通过 |
| owned process/session/finalization、scanner/containment、Schema 增量 | 首次八文件 313 passed / 1 个既有 inventory 失败，26.40s |
| 既有失败与本次改动区分 | clean main `88128c3` 同测试以 11!=10 失败，0.34s |
| 修改后的启动门与 Schema 复验 | 31 passed，7.67s |
| generator contract RED | 合法 11 图拒绝/缺图错误 10 图放行：2 failed / 1 passed，0.77s |
| generator 与最终 Schema GREEN | 11 passed，2.55s，含缺/多/同数量替换图零写入拒绝 |
| discovery 直接 caller 回归 | 34 passed，1.08s |
| Ruff check / format check / strict mypy | 最终六个 Python 文件全部 PASS |
| diff whitespace/路径检查 | `git diff --check` PASS；改动在 task.json 明确 allowlist 内 |
| 独立审查 | 独立 reviewer 最终 PASS，无阻断；其实际 35 passed / 5.89s，diff check PASS |

未跑全量，未访问生产 HTTP/SQL、发送生产信号、审批、恢复 K1、提交/推送或部署。生产 PID802 的旧 UNKNOWN 没有被改写。正式集成与独立 Host 维护由 Root 根据当前可信事实处理，不能将新 launcher 成功测试视为旧执行停止证明。

## 交接与回滚

本任务代码/契约与增量质量门、独立审查已完成。Root 明确授权在独立分支提交精确文件；审查结论已追加到 `validation.md` 和 `task.json`。提交不包含 Root 单独处理的生产维护事实，不合并、推送或部署。

回滚必须先完成实际受控停止，再同时回退 helper/两个 caller。保留旧 UNKNOWN、Run/Operation/lifecycle 原字节及原需求现场，不回填 READY 或通过直接改库跳过用户审批。
