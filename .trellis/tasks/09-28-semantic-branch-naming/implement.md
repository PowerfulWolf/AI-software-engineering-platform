# 实施规划

实现已贯通生产与恢复，本地质量门已完成；实际结果与验收限制见 verification.md。
验证报告交付后用户已明确要求完成任务并提交、推送；工程任务按此授权关闭。
续接时保留已改正的同名需求夹具，修正 CLI capture 夹具的旧摘要，并补齐干净语义工作树
恢复的 Task 归属凭据。跨 Task 冒领真实 Git 回归先失败再通过，碰撞与完整性保护未放宽。

1. 读取 Git、领域/持久化、Product/dispatch、恢复相关规范；完成 PRD 收敛和跨层字段设计。
2. 先增加分支契约及真实 Git 回归：两种类型、非法输入、碰撞、同 Task 续跑、独立 verifier、漂移拒绝。
3. 接入 Product 命名意图、批准/Task/dispatch 传递与生产强校验；同步涉及的 Schema 和模型输出协议。
4. 接入 worktree 创建、恢复、恢复干净现场及所有权检查；捕获记录保留名称并兼容旧摘要。
5. 补独立 recovery/remediation 的名称来源、精确计划绑定和冲突处理；同名其他 Task 必须拒绝。
6. 同步前端 Product/恢复计划/交付结果展示、文档与 executable spec。
7. 分层验证并检查存量恢复：focused unit/contract、真实 Git、相关 MySQL（可用时），再运行离线回归、Node、Ruff、Mypy、build。
8. 记录实际结果/跳过/局限/存量处置；初始阶段保留未提交改动，后续按用户明确授权提交、推送。

## 必须覆盖

- 新 feature/bugfix 真实创建；普通续跑/重启名称稳定；语义名同名冲突不覆盖。
- 执行次数变化不改变分支；QA/Review 返工类型遵循确认后的需求语义。
- 新格式 capture→plan→approval→successor→candidate；旧格式同链不改 bytes/hash。
- 跨 Task/仓库冒用分支、错误 HEAD、dirty preserved worktree、路径别名及任意 ref 注入拒绝。
- ProductSpec/Task/恢复计划字段篡改、名称变化导致的旧批准失效；新生产入口不能借 legacy 默认值绕过规范。
