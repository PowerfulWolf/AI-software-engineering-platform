# 增量验证与边界

新增实际final-input回归先因缺少typed exception/receipt变红，再完成真实preflight gate后转绿。
- receipt正向/负向/legacy约束：6 passed。
- final payload/native wrapper/schema/Responses/before-start + verifier preparation既有回归：31 passed。
- 6个相关文件 strict mypy通过，Ruff与diff检查通过。

记录内容只包含真实claim、Task/context digest、预算和estimate；无prompt/body/key。保留现有native verification receipt。
store故障、身份漂移或已有invocation拒绝wait发布。无退款/重试计数写入，无provider调用。

存量数据处置：此writer不改旧K1；旧terminal容量故障必须通过另一路显式legacy_terminal_context
观察与受控successor恢复，不补造旧request/final count。发布前同时集成classification与恢复consumer；
仅writer单独上线不能解决旧任务。回滚受控停服后恢复代码，保留已发布receipt及失败历史。
