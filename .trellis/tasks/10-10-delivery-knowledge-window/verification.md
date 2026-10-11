# 验证记录

## 前提

- 仓库缺少 `.trellis/scripts/get_context.py`；按 `.trellis/spec/core/index.md` 定位并阅读规范。
- 已阅读 architecture/contracts、Python runtime、active knowledge、delivery recovery、
  timeout classification 与 recovery thinking。
- 不运行生产模型，不操作 ASE 生产，不提交；MySQL 测试等待 root 协调独占测试库。

## 红测与绿测

红测（生产代码尚未修改）：

```sh
.venv/bin/python -m pytest -q \
  tests/knowledge/test_delivery_context.py::test_native_knowledge_calls_use_the_admitted_role_window \
  tests/knowledge/test_consultation.py::test_structured_knowledge_calls_share_the_admitted_role_window \
  tests/recovery/test_progress_source.py::test_prior_accepted_progress_survives_exact_next_attempt_knowledge_failure \
  --tb=short
```

结果：**15 failed / 18 passed in 2.37s**。6 个 Native 长窗口、8 个 structured 长窗口
（包括 Manager）实际都收到 600 秒；精确本地窗口到期的恢复来源被拒。60 秒窗口和旧原因通过。

实现后纯离线增量：

```sh
.venv/bin/python -m pytest -q tests/recovery/test_progress_source.py \
  tests/knowledge/test_delivery_context.py tests/knowledge/test_consultation.py --tb=short
```

结果：初次 **108 passed in 1.15s**，补齐四尾事件 from/to 与 progress Task 身份拒绝后
为 **117 passed in 1.24s**。包含精确原因、四尾事件/attempt/source/progress/context/
candidate 拒绝矩阵、活跃 claim/WorkItem gate，以及候选恢复的独立 consultation 证明门禁。
该候选单元测试只证明新增原因到达后续证明门禁，不能证明完整候选已获得执行授权。

Ruff、格式化检查和 strict Mypy 最终对本任务三个生产文件、五个测试文件全部通过。
类型检查使用 `MYPYPATH=src .venv/bin/python -m mypy --strict`，检查文件与 Ruff/格式检查
均为本任务的八个 Python 文件；`git diff --check` 通过。

MySQL collect-only 确认本次唯一新增 node：

```text
tests/recovery/test_native.py::test_budget_exhausted_coder_progress_is_a_recoverable_native_source[local_timeout-False]
```

root 已协调上一测试完成并授权独占运行；启动前真实调用测试数据库命名 guard，且只在内存
比较测试与生产解析后的数据库名，确认不同。pytest 子进程仅接收 PATH/LANG/LC_ALL 与测试
DSN，不传生产模型密钥或生产 DSN。

### 旧参数 fixture 的根因与准确化

第一次单例 **1 failed in 1.40s**，外层异常为 `Task dispatch mismatch`。只读异常 frame
诊断实际显示 immutable 字段完全一致、Task 仍 `IMPLEMENTING / attempt 1 / revision 2`，
checkpoint 同 revision，真正的失败为 `Delivery stopped safely (CoderSliceRejected)`：旧
`ContinuedCoder` 写死 `remaining_step_ids=("finish_change",)`，与现代冻结 slice 中的真实
step IDs 不符，第一轮进度根本未被接纳。不是 Task/dispatch 契约需要放宽。

经 root 同意，仅在本参数用例已有 run wrapper 用 `request.work_slice` 的输入 completed
与 selected/later IDs 准确声明草稿进度，不宣称新工作完成、不改通用 factory 或生产 gate。
修正后 **1 failed in 1.96s**，第一次公开 `entry.approve` 正确返回 `DELIVERING`，旧用例仍
预期一次调用就耗尽全部工作额度。现代串行 Worker 保留第一轮进度后需要新的公开推进调用。

经 root 同意，该用例使用 `entry.resume` 有界推进，硬上限来自冻结工作额度（本 fixture 为
3）；不直接调用编排或写 Task。默认现代工程 policy 会把该原因转为非终态等待；因此历史
terminal 知识失败参数用公开 product-only Principal 从最初 dispatch 自然冻结无 engineering
policy 的来源，另一个可信工程职责 Host 执行 scope/恢复审批。源码与冻结 Task/dispatch
均不改写，现代默认 WAITING_DEPENDENCY 行为保持。

### 真正的封存差异缺陷与最终结果

历史来源变得准确后，source reader 已真实通过，但完整现场 gate 仍拒绝。root 对生产 K1
只读核对证明这是实际缺陷：route 中原始 provisional progress 和 store 中 accepted progress
正文相同，只有平台封存的 integrity/digest/time 不同。固定 fixture seal 会掩盖生产问题。

先新增 provisional→sealed 正例获得 **1 failed in 1.14s**，再将 workspace gate 的对象相等
改为既有 canonical `artifact_digest` 相等，并显式要求 accepted progress 类型。Task/source/
Context/run/正文仍属于完整摘要，不被排除；重复 source reader 和真实 stopped gate 保留。

```sh
.venv/bin/python -m pytest -q tests/recovery/test_progress_source.py \
  tests/knowledge/test_delivery_context.py tests/knowledge/test_consultation.py \
  tests/recovery/test_workspace_snapshot.py::test_successful_progress_keeps_verified_existing_recovery_contract \
  --tb=short
```

结果：**128 passed in 9.47s**。含真实 provisional/accepted seal 差异正例，以及内容、source、
Context、producer run、Task、缺 accepted artifact、未知停止、reader 拒绝和实际失败 Run 的反例。

在同一隔离测试库、相同环境 guard 下，最终仅运行以下新增 MySQL node：

```sh
.venv/bin/python -m pytest -q \
  'tests/recovery/test_native.py::test_budget_exhausted_coder_progress_is_a_recoverable_native_source[local_timeout-False]' \
  --tb=short
```

结果：**1 passed in 190.83s**，进程 exit 0，fixture 已释放并清理测试事实。
真实经历第一轮进度接纳、第二轮知识本地窗口到期（第二次原生 Coder 从未启动）、来源读取、
scope 精确审批、恢复计划准备、artifact 篡改/后续执行/工作区漂移/错误批准摘要拒绝，再经
新 Task 独立 Coder/QA/Reviewer 到 DONE。原 terminal Task 与全部事件前后相同。
这是隔离离线生产组合回归，不能宣称生产 K1 已交付；生产继续由 root 在安全部署后推进。

## 前端与独立审查

root复核真实生产只读投影：原页面同时要求批准尚未准备的方案、又说无需产品操作，
现有准备按钮还藏在工程管理折叠区。精确STOPPED的Coder知识时限现给“继续交付”先
检查/准备、准备好才批准的步骤；queued/running、读取不可用、缺服务能力和已有审批
分别给实际下一步，不建立新权限或伪造角色启动。

专用Node8/8与Chrome1/1由独立check重复通过；390/1440布局、busy恢复、零POST验证通过。
最终合并讨论区域的去重修复后，root运行以下相关Node增量51/51通过，JS语法/diff通过：

```sh
node --test tests/team_view/knowledge-preparation-timeout.test.cjs \
  tests/team_view/product-execution.test.cjs tests/team_view/operation-progress.test.cjs
```

旧大型ui.test队列聚合1≠2已用b2d2e68干净资产隔离复现，不隐藏失败或改无关预期。
独立check确认读取资格→同scope活动请求→服务能力→准备指引的顺序，现成审批/执行
UNKNOWN/QA与Reviewer恢复优先级保持。所有前端资产待安全维护部署后再核验生产。

## 独立后续事项

Recovery Task 冻结策略可能遗漏知识窗口增长配置，属于独立 followup；本任务不补旧 Task policy。
