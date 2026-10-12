# 增量验证记录 · 2026-10-12

## 环境与范围

- 隔离工作区：`/Users/zhangjunshuai/workspace/code/ase-trusted-query-spawn-gate`。
- 基线：`88128c3cf31804ed6f6e3eeff52e03382f250c09`。
- 实际平台：Darwin；解释器为主维护目录已有 `.venv/bin/python`，以 `PYTHONPATH=src` 导入本树实现。
- 依照用户约束只跑增量。真实测试只启动/清理自己的 fixture 子进程；没有生产 HTTP、SQL、信号、审批、服务启动或 K1 工作区写操作。
- 本树没有 `.trellis/scripts/get_context.py`；已直接读 core index 指向的 architecture、contracts、python-runtime、owned-session-stop 和 recovery-thinking。

## RED / 原因归属

原调查已捕获实际 Darwin `/bin/ps` 为 alive effective-root setuid 进程，初始出生身份读取得到 EPERM；原始扫描返回 PROCESS_SCAN_INCOMPLETE。它在目标工作已开始之后才尝试捕获归属，且普通极短命目标另有先退出的竞态。本次 helper 改变真实启动顺序；从不把 EPERM/缺 PID 解释成历史 stop。

接手的 WIP 最初 18 个真实启动门测试通过（4.15s）。补充三项非法 JSON/环境帧与实际 exec PID/SID、ACK 不可写、Popen 启动失败 FD 清理后，启动门共 24 个测试。

八文件增量回归首次结果：313 passed / 1 failed（26.40s）。唯一失败是既有 `test_owned_session_stop_schema.py` 的 `len(paths)==10`；基线 `d4d6f32` 已新增 queue-consumption Schema，实际为 11。随后在 clean main `88128c3` 独立运行同一测试，完全相同失败（0.34s），证明它不是本次启动门引入。Root 明确扩展本任务范围后，以 11 个精确文件名集合替换计数并保留全部逐图、负向和临时再生成断言。

同一预存缺陷也存在于 `scripts/sync-owned-session-schemas.py`。先写临时 fixture 测试，RED 为 2 failed / 1 passed（0.77s）：合法 11 图被拒绝、删掉 queue-consumption 后的错误 10 图反而通过并写入。Root 授权后，生成器改为独立精确名称集合；增加同数量文件替换场景，确保不能仅靠数量放行。没有写生产 Schema。

## 命令与结果

共同前缀：

```sh
PYTHONPATH=src /Users/zhangjunshuai/workspace/code/AI-software-engineering-platform/.venv/bin/python
```

首次八文件回归（313 pass / 1 个上述预存失败）：

```sh
-m pytest -q -p no:cacheprovider \
  tests/execution/test_owned_query_spawn.py \
  tests/execution/test_owned_processes.py \
  tests/execution/test_owned_session_stop.py \
  tests/execution/test_owned_session_inspection.py \
  tests/execution/test_owned_record_finalization.py \
  tests/manager/test_legacy_local_execution.py \
  tests/manager/test_legacy_containment.py \
  tests/contracts/test_owned_session_stop_schema.py
```

修正 inventory 后，只复跑受修改影响的两文件：

```sh
-m pytest -q -p no:cacheprovider \
  tests/contracts/test_owned_session_stop_schema.py \
  tests/execution/test_owned_query_spawn.py
```

结果：31 passed（7.67s）。其余上述已通过的文件没有再改，不重复跑。

验证 discovery 的直接 caller 回归：

```sh
-m pytest -q -p no:cacheprovider \
  tests/manager/test_python_verification_discovery.py \
  tests/manager/test_owned_verification_discovery_diagnosis.py
```

结果：34 passed（1.08s）。

生成入口修复之后，只重跑受影响的 Schema 契约文件：

```sh
-m pytest -q -p no:cacheprovider tests/contracts/test_owned_session_stop_schema.py
```

结果：11 passed（2.55s），包括合法完整图修复与缺图/额外图/同数量替换图均在任何写入前拒绝；原完整 stop graph、负向、临时 repair 再生成均保持通过。

对 helper、两 caller、启动门测试、Schema 测试、Schema 同步脚本运行 Ruff check、Ruff format --check 和严格 mypy（cache位于 `/tmp/ase-query-gate-mypy-20261012`）：最终均 PASS（6 文件）；`git diff --check` PASS。

## 正反边界

- 真实 Darwin setuid `/bin/ps` 三次、真实 scanner `_query`：原 output 不变、registry 可清空、原 `require_stopped` 通过。
- 12 次快速 Python、10 次重复查询：capture 先于目标执行，不留下 registry/父 control FD。
- target 实际 PID/SID 等于原 Popen PID；精确 argv、env、stdin、cwd、二进制 stdout、stderr 不变；目标无内部 ACK FD。
- 空/显式环境保持精确，Python bootstrap 的 locale/macOS环境修正不进入目标。
- 初始 capture 或二次 observation 拒绝：target marker 不存在，真实 bootstrap 被清理，UNKNOWN 保留且 `require_stopped` 拒绝。
- ACK EOF/错误/部分/超限/非法 JSON/非字符串环境、ACK 写失败或不可写：不执行目标；父 FD 无泄漏，失败有界。
- target exec 权限拒绝：固定失败码，不输出原异常/密钥；实际 bootstrap 完整结束后 registry 才可清空。
- 已逃逸进程持有输出管道：原 timeout/EOF 判据继续拒绝，UNKNOWN 不清除。

## 存量数据处置、限制与回滚

无迁移，不改历史 Operation/Run/Task/queue/approval/lifecycle 或旧 stop bytes/hash。生产 PID 802 的既有 UNKNOWN 不因新测试/新 launcher 消失；独立 Host 维护由 Root 依据真实新核验执行。该启动门只供两个既有可信 caller 使用，没有 Agent tool、角色权限、native Coder spawn 或 owned-session 判停规则变化。

保留现有 owned SID proof 的范围；未观测到、通过 setsid 逃逸且关闭输出的后代仍超出该证明，不能声称完整进程树 containment。活着 setuid 目标如果超时或身份不可读，仍拒绝。固定一秒 ACK 发布窗口不能代替 caller 原输出/执行时限。

独立 reviewer 最终 PASS，无阻断项；Root 转交的独立实际复验结果为 35 passed（5.89s），独立 `git diff --check` PASS。review 范围覆盖 capture-before-exec、失败不放行、ACK/FD、原 stop/UNKNOWN、精确 inventory 与 caller 边界。review 由独立 reviewer 作出，作者没有自判 verdict。

提交前应用 finish-work 复核已执行质量证据与规范的真实签名、错误矩阵、Good/Base/Bad、断言点；无 HTTP/API/数据库模型变化，无迁移。只进行 Root 明确授权的独立分支代码提交，生产维护事实不混入本提交。未合并、推送或部署。回滚需先完成实际受控停止，再一起回退 helper/两 caller，保留全部未知历史，不补造 READY。
