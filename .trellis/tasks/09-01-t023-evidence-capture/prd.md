# T023 PRD：Evidence Capture

## 目标

把每次受策略约束的命令、候选 diff、测试结果和 Agent provider usage 变成可定位、脱敏、带
SHA-256 的不可变 evidence，并为一个 Agent Run 生成可重放的 evidence manifest。

## 必须满足

1. command evidence 必须保留 tokenized argv、绑定 cwd、return code、bounded stdout/stderr、
   duration、truncation 和 timeout/rejection/start failure；
2. diff evidence 必须绑定 base/candidate revision、changed paths 和 bounded redacted patch；
3. test evidence 必须引用同一 run 的 command evidence，明确 framework/suite/outcome；
4. Agent usage evidence 必须绑定 provider/model/status/duration、可选 token usage 和 typed error；
5. 所有 evidence record 和 run manifest 使用 canonical JSON、SHA-256、atomic write、immutable put，
   replay identity 冲突 fail closed；
6. command output、diff、error、argv、cwd 和 provider payload 中的常见 secret 不得进入持久化明文；
7. schema 与 Python models 必须保持 discriminated union 一致，invalid/partial evidence 不得被下游
   当作 verdict。

## 非目标

- 不决定 QA/Review verdict；
- 不允许自由文本执行 shell；
- 不引入数据库、消息队列、向量库或 provider 专用类型；
- 不保存完整 provider 原始响应。
