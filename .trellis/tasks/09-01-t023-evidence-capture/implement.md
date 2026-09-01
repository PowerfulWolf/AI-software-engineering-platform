# T023 Implementation Notes

# T023 Implementation Notes

T023 已完成。Evidence 层封存每个独立 Agent Run 的可验证事实，不解释事实为 QA 或 Review
verdict：

- `evidence/models.py` 定义 command、diff、test、Agent usage discriminated records 与 run
  manifest；digest 排除自身字段，临时全零 digest 只允许在 sealing 前的内存构造阶段；
- `evidence/capture.py` 复用现有 `CommandExecutor`/`AgentAdapter` typed ports，保存 tokenized
  argv、cwd、返回码、限长输出、超时/拒绝/启动失败、候选 diff、测试链接及模型 usage；
- `evidence/store.py` 使用 canonical JSON、fsync + atomic rename 和 immutable put；读取时重新
  校验 schema、文件名 identity、record/manifest digest 及 run 引用完整性；
- `redaction.py` 成为 Context 与 Evidence 共用的确定性 secret-redaction seam；不保存完整
  provider 原始响应；
- `schemas/evidence.schema.json` 与 `schemas/run-evidence-manifest.schema.json` 对齐 Python
  discriminated unions；`tests/evidence/` 覆盖正常、非法、重放、篡改、边界和失败路径；
- Agent `AgentUsage` 为 provider-neutral typed token counts，OpenAI-compatible adapter 只提取
  标准 usage 字段并继续返回 typed success/failure。

不在本任务范围内：工具调用协议、QA/Review verdict、数据库/队列、provider 原始 body、自由
文本 shell 执行。
