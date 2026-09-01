# 实现计划

1. 先在 `tests/agents/test_openai_compatible.py` 固化 transport、prompt、成功、失败和 replay seam。
2. 新增 `agents/openai_compatible.py`：typed prompt/transport、urllib 实现、响应提取、错误映射。
3. 从 `agents/__init__.py` 导出公共类型，保持 Fake 与真实 adapter 共用 Protocol。
4. 增加 ContextStore 与 FileRunContextBuilder 登记 seam，保证真实 adapter 可按 ID 装配。
5. 同步 `docs/contracts.md`、`docs/prompt-protocol.md`、`docs/tech-stack.md`、README、核心 spec。
6. 完成 verification 记录后运行全套质量门。
