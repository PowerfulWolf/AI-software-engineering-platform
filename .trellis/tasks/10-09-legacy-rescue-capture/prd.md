# 修复保留草稿的源码敏感信息误报与恢复失败展示

## 问题

重启服务后本机进程调查已经通过，但旧 K1 的恢复准备在完整工作区捕获阶段失败。
通用 `secret_assignment` 规则把 `password=settings.password` 和
`secret = foreign / "secret.json"` 当成了秘密字面值。与此同时，前端只显示后续泛化的
等待处理报告，用户看不到最新恢复准备的失败原因。

## 验收标准

- 保留代码快照和其后续 baseline/context 校验在同一受限源码分类规则下允许明确的属性引用、
  路径表达式，原始 bytes、patch、digest 不改变。
- 明文 password/secret/token/api_key、Bearer、OpenAI/AWS/GitHub key、PEM 和不明确的
  dotted 值继续 fail closed；通用日志、URI、知识和 evidence 脱敏契约不变。
- K1 的上述普通源码可完成恢复方案准备，不绕过权限、完整文件清单或历史停止确认。
- 捕获拒绝返回固定中文安全原因和维护下一步，不发布秘密内容。
- 需求详情和处理报告展示最新、同 Project/Requirement/Task/checkpoint 的恢复准备 FAILED/INTERRUPTED；
  不生成方案、不显示批准入口，并保留操作 ID、错误码和安全诊断供工程核对。
- 不改数据库结构、旧 UNKNOWN、历史草稿、Task、审批或用户工作区。

## 验证范围

仅运行增量 redaction/capture/baseline/context/legacy-console/browser 相关测试、Ruff、严格 mypy、
format 和 diff check；全量测试由用户运行。
