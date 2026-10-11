# 交付知识准备窗口与保留进度恢复

## 问题与目标

K1 第一轮 Coder 已真实提交并被平台接纳 `coder-progress`，第二轮在知识评估阶段到达
本地 600 秒窗口。知识咨询对 Delivery 角色存在独立隐藏的 600 秒上限，未使用调用方已经
准入的有限角色窗口；同时终态恢复的既有精确原因集合只覆盖认证失败和旧 TIMEOUT，
漏掉当前实际写入的 `coder knowledge preparation reached local time limit`。

让交付知识 intent/assessment 使用已准入的角色窗口，并让上述精确历史形态沿既有
保留进度恢复路径提出方案。保留原 Requirement、原 Task 与历史记录，不补造调用或停止事实。

## 允许范围

- `src/ai_software_engineer/recovery/progress_source.py`
- `src/ai_software_engineer/knowledge/agents.py`
- `src/ai_software_engineer/recovery/workspace_snapshot.py` 的成功进度摘要比较
- `tests/recovery/test_workspace_snapshot.py` 的对应正反边界
- `tests/recovery/test_progress_source.py`
- `tests/recovery/test_native.py` 的 `knowledge_failure` 参数用例
- `tests/knowledge/test_delivery_context.py`
- `tests/knowledge/test_consultation.py`
- 本任务目录

不修改 transient 分类、重试额度、旧 Task policy、生产数据、服务状态或审批。
其他维护者同时工作；不回退或修改其他人的文件。

Root另负责此问题的前端窄修复：app.js的知识超时解释与阻塞下一步、专用
knowledge-preparation-timeout.test.cjs、ui.test.cjs一条文案预期及相关两个spec。
真实页面此前同时要求批准尚未准备的方案、又说无需产品操作，虽有“继续交付”按钮，
用户无法知道步骤。只有同scope当前BLOCKED、可信STOPPED、Coder精确知识时限原因，
且没有engineering unknown或现成审批优先级时，提示“继续交付”先检查/准备，方案
准备好后才核对并批准。读取门禁或服务能力不可用须给实际说明；QA/Reviewer不承诺
尚未验证的恢复入口。不改变执行状态、审批、controller或后台权限。

## 验收标准

1. 非 MySQL 红测重现 1200/1800 秒角色窗口被截为 600 秒，以及本地窗口到期原因被拒绝。
2. Native Coder/QA/Reviewer 与 structured 各角色的两次知识子调用都收到调用方窗口；
   60/1200/1800 秒边界有覆盖，最终 structured 输出窗口保持一致。
3. 仅精确本地到期原因新增可识别；相邻 attempt、完整四尾事件、Task/source/progress、
   route/context、一致 artifact 与无 candidate 的约束仍拒绝不一致事实。
4. 活跃 claim/WorkItem、后续执行、现场漂移和非精确审批仍被既有 gate 拒绝。
5. 真实隔离 MySQL 参数用例覆盖认证失败和 typed TIMEOUT/local_execution_limit；
   仅经 root 协调测试库空闲后执行，不并发清库。
6. 路由中的 provisional progress 与平台封存 accepted progress 使用相同 canonical 正文
   摘要判断，不因平台新增 integrity 时间而误拒绝；Task/source/Context/run/正文变化仍拒绝。

## 增量调查发现

真实K1第一轮route与accepted artifact仅integrity不同：route为provisional，平台artifact
store已校验封存；二者canonical SHA同为a5a24a02fd561659e685447b95572809413d24ca4a9b0ee7eccd1323bfcbb505。
完整对象相等错误地拒绝合法封存过程。按既有artifact_digest契约只排除integrity，独立
reader、run/source、停止与现场复核保持；不能通过给fixture伪造相同seal回避真实缺陷。

## 存量处置与回滚

本任务不修改任何已有事实。兼容 reader 部署后，原终态 Task 仍为终态，平台应从同一
Requirement 提出新的精确恢复方案，校验停止、现场与审批后才创建 successor。
不得把知识调用当作原生 Coder 执行或 verdict。回滚仅撤销本任务源代码/测试变更；若已经
消费恢复方案，保留兼容 reader 和全部 immutable 历史，优先向前修复。
