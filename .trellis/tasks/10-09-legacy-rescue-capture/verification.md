# Verification

本轮未替用户操作 ASE、审批、启动 Coder、重启服务或改生产数据。只跑相关增量。

## Python 增量

最终核心：

```bash
.venv/bin/pytest -q --tb=short tests/context/test_source_secret_detection.py \
  tests/git/test_mutation_capture.py tests/manager/test_execution_baseline_context.py \
  tests/web_console/test_legacy_rescue_acceptance.py
```

**83 passed in 47.84s**。源码边界、Git完整capture/wire/verify、三角色baseline replay/required
Context、typed捕获WAITING与无审批；source36用例含最后新增huge count回归。

本轮同时运行 `test_capture.py`、`test_builder.py`、`tests/evidence/test_capture.py`、
`test_legacy_snapshot.py`、`test_local_legacy_rescue_schema.py` 的57个原增量用例；
结合当时source35+mutation30+context3+console14得到 **139 passed in 67.27s**。
随后新增huge-count1用例由最终83和独立source36覆盖，相关Python用例总140个，未跑全量。

```bash
.venv/bin/pytest -q --tb=short tests/manager/test_legacy_rescue_delivery.py \
  -k 'False-False-True or False-True-True' --maxfail=1
```

**2 passed, 3 deselected in 47.82s**。独立测试MySQL、真实Git、fake native角色；生产公开Host
同Task/独立Coder-QA-Review完整恢复及绑定到SQL消费前崩溃重放，无真实模型调用。
两条Starlette/httpx原有兼容性warning无失败。

修改的11份Python代码/测试 Ruff、format check、strict mypy通过；diff check通过。

## 前端增量与独立复核

```bash
node --check src/ai_software_engineer/team_view/app.js
node --test tests/team_view/engineering-wait.test.cjs tests/team_view/operation-capabilities.test.cjs
NODE_PATH=/tmp/ase-rescue-ui-test-deps/node_modules node --test \
  tests/team_view/browser/legacy-rescue.test.cjs tests/team_view/browser/engineering-wait.test.cjs
```

**42个轻量用例、14个真实Chrome用例通过**；FAILED/INTERRUPTED复制报告、后续HANDLE不遮盖、
11类外来/旧绑定、stale审批及typed捕获WAITING。未触发生产ASE操作。
独立review发现quoted/config/f-string/diff计数漏洞，均提交前修复；独立source36、
先前mutation65增量通过，最终无源码安全blocking和前端blocking。

## 存量数据处置

目标 `task_dc5cf0aee44e5ffe0cb600557204e0d0`，原Run
`run_9b76fb2865144f2abb6407923320ec4e`。使用真实原 invocation permissions/原WorktreeRef，
24个变更和未跟踪文件可读；dirty/complete各24mutations，capture→wire→to_capture完全一致。
原工作树全部2,000条目（含模式/内容）的前后SHA
`73a2e68b582bd19ac383ec52e4791fed6fbddb3fc1a2153aed2c0383dbff5213`相同，
Git index前后SHA `af9cc1d7a79722081b89707083968acc89054d3767bdd084b5f046841361d293`相同。
没有生成plan、写Host/SQL/Task/审批或修改草稿。

无需改库/迁移/重建需求。旧UNKNOWN、失败Operation和历史摘要完整保留；前端读取原事实显示
当前失败。用户在服务空闲时运行 `scripts/ase-console-service.sh restart` 加载后端修复并刷新，
在原需求点击“修复后重新检查恢复前提”（或现有准备按钮），查看精确方案后自行确认真实旧
执行及派生工具已结束，再批准。检查不等于历史停止证明，审批仍由用户完成。

当前真实 `codex sandbox` 活动在检查时仍会保守阻塞；不kill或豁免真实执行，需要其结束。
历史首次survey incomplete无errno，不能推断具体竞态；后三次实际sealed survey为空且进入
capture失败，证明本轮误拒绝发生在源码捕获。

## 已知边界与回滚

源码例外仅.py的可解析语法/明确表达式，未知语言或不完整diff fragment继续保守拒绝；
v1 recovery、通用日志/知识/Evidence脱敏未扩展。没有后台自动审批或历史停止重建。
外部会话提交`4ddaf10`和`55742de`的help/restart文档保持，不回滚它们。
如需回滚本提交：受控停服→`git revert <本提交SHA>`→启动并刷新。旧历史/草稿/审批不可删除。
