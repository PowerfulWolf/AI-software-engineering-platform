# 实施与验证

需求详情始终挂载懒加载知识历史；阶段进入缓存键，避免从等待转为交付后保留过时表单。
历史显示 resolution ID、approval reference 和 recorded actor。无 API/Schema 或状态写入变化。
Operation 调用区明确显示已完成的阶段诊断；关联当前 Project/Requirement 的角色记录入口，
仅匹配当前角色的非终态 RUNNING+LEASE_VALID 事实显示执行/心跳，不推断实时 provider 进度。

## 验证

- 新三项 Node 回归先 RED：3 failed，复现历史入口消失、同 checkpoint 旧表单及空诊断误导。
- 修复后 `node --test tests/team_view/knowledge-gap.test.cjs tests/team_view/delivery-status.test.cjs tests/team_view/ui.test.cjs`：44 passed / 133ms；独立 QA 同命令 44 passed。
- 既有 retained-origin 用例在变更前 HEAD 也报 null != 设计；旧修复已将等待流程改为 blocked，
  本次只把过时测试更新为断言 blocked 且没有 current 动画，不改流程生产逻辑。
- node --check、git diff --check 通过。独立 Reviewer 无问题。
- QA 额外内存探针验证同 ID 跨 Project 的旧异步响应隔离、GET 懒加载、历史无表单和
  审批字段 HTML 字面量安全呈现。
- 生产 GET /app.js 字节与本地已验证源码完全一致，静态更新无需重启服务。
- 将生产 HTTP 返回的真实 Team 与 knowledge-gaps 数据交给该 app.js 的 DOM fixture：
  resolution 99f12413 完整答案可见、无重复提交表单。14:17:58Z 当前 Task 已真实 BLOCKED，
  activity 正确为空，没有将 CLOSED 租约渲染为执行中。

## 存量数据处置

无需改库，既有问题 f3a2673b 和答复 99f12413 保留。用户在需求详情普通刷新后点
“查看知识核对记录”，可核对原问题/答复/依据。未回填历史模型调用或伪造 provider 活性。
浏览器工具认证仍不可用；上述是实际静态源码+真实API数据的fixture验证，不宣称Chrome实测。

## 交付事实与风险

K1 Coder 于 14:14:38Z 完成，候选 bd40ce051cf8f0fcc70009f493d8fd2cba32d833；
QA 于14:16被全仓只读快照2MB上限拒绝，尚无QA verdict。Manager协调额度已耗尽。
该独立前提另建任务处理；本任务仅修复展示。Coder报告还执行了全量非MySQL测试，
与用户只跑增量的偏好不符，后续受控验证必须固定精确节点，不重复该全量执行。
无全量测试由本任务执行。回滚 app.js 到fa3c96f，保留所有事实与候选。
