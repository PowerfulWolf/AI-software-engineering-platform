# 保留草稿的执行基线上下文投影

真实 K1 第 11 轮 Context 的 execution.baseline 为 595,135 字符，其中完整旧补丁
566,420 字符。保留草稿已在同一工作区 materialize 并由平台独立核验，重复把补丁作为
JSON 字符串包装使最终输入超出本地 256,000 token 预算。这里只修上下文设计，不推断
该历史模型失败的首因，不改写它或授予继续执行。

验收：保留模式在三角色新 Context 使用 v2 有界投影，完整证据仍逐次读取校验；缺失
verifier 或证据失败关闭。reapply 完整正文、旧 Context、native epoch、同 SHA 独立验收
和 exact Task/source/authority 契约全部保持。Root 另实现最终序列化预算门。

验证：先用生成大补丁的真实 builder 增量回归重现膨胀，再验证 v2、旧 v1、缺失与篡改
证据、候选源码和公开 Host delivery 回归；Ruff/strict mypy。不得跑全量测试。
