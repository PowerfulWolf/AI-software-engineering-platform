# Contract
静态wire/schema字段不变。当前请求的coder-progress.content.checkpoint_sequence必须等于
AgentRequest.attempt，不能使用队列checkpoint_sequence、Task revision或上次检查点+1推断。
由provider输出Schema、prompt绑定和live结果验证共享同一不变量。
全局持久化AgentResult模型不能因新增校验使旧非法SUCCEEDED结果无法读取；验证位于live接纳边界。

| Case | Outcome |
| --- | --- |
| attempt4/progress4 | 按现有身份/权限/现场规则继续校验 |
| attempt4/progress9 | INVALID_OUTPUT，原始内容保留，无候选/QA/重放 |
| 旧封存progress9 | 历史可读，仍不能通过编排接纳门 |
| 非progress artifact | 原逻辑不变 |
