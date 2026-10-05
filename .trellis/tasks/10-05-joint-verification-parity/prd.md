# 联合设计与原生验证契约一致、明确反馈及存量恢复

## 已确认问题

K1 的联合 Designer/Planner 已产出合法外层 Schema 的设计与计划；进入原生单仓交付时，
同一设计的检查策略被原生 AcceptanceDesignMapping 拒绝：
`inspection cannot weaken the approved verification levels`。
两个 acceptance 分别将 source inspection 混合集成验证、document inspection 混合安全验证。
联合校验未检查原生同一约束，编排只显示泛型“Designer 未发布已验证的 planning handoff”。
当前 native child 没有 Task、候选、QA/Review 或有效执行 claim；所有已产生模型调用已完成。

## 目标与验收

- 联合设计接纳前复用原生 inspection/verification-level 约束；Designer 及时收到验收 ID
  与具体问题，不允许较弱检查替代已批准集成/安全验证。
- native deterministic bridge 保留真实已验证输入与错误，不将平台接线或产物契约问题
  泛化成无法行动的“交接缺失”，所有产品展示阻塞原因中文。
- 不放宽原生验证、Schema、权限或无自我批准边界；仍由独立 Designer 修正设计，Planner
  重新产生受影响计划，再进入 NEW Task 和原生 Coder/QA/Review。
- 当前 K1 必须走精确 scope/source/checkpoint 绑定的公开 typed 恢复；保留旧设计/计划/失败
  历史与产品批准，不直接改库或改 journal、不退预算、不手工补验收或伪造交接。
- 已有安全接续能力优先复用；若确实缺少能力，先定义最小恢复契约、明确无 Task/无候选
  边界和精确批准，禁止普遍重试 INVALID_OUTPUT 或任意复活终态 Task。

## 验证与回滚

先用当前失败策略复现 native/joint parity contract，测试合法、非法和边界策略；fake 上游
和 native bridge 测试须经过实际生产组合 seam。存量恢复正向与 scope/checkpoint/source/
任务存在等反向 gates 均须验证。只运行相关增量测试，全量需要用户另行运行。
后端发布在确认平台空闲后进行，不读取或输出 runtime.env；重启沿用可信服务脚本。
回滚代码并保留新旧封存历史，不删除账本或恢复已拒绝设计为有效输入。
