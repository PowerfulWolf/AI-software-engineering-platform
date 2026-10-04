# 上游角色冻结规则输入投影

目标：新 K1 的完整 checkpoint 约 1,205,326 字节直接进入 Product/Designer/Planner 请求；复制 full native corpus 导致不必要的大输入，虽然已存在可重验知识检索。复用 native_rule_prompt_sources，仅在模型 payload 投影，原 checkpoint 与 knowledge snapshot 保持完整。

范围：multi_directory/service.py；Manager stage/verification coordination 的用户说明语言；相关增量测试和规范。模型主路由仍为 gpt-6.1-sol，保留现有备用路线，不改变 Product 精确审批或 QA/Review。

验收：三个上游 producer 都保留完整 scope/Product/Approval/Design/Plan，native AGENTS 正文保留，其他 native bodies 通过引用和 verified retrieval 读取；backend.client 接收未经修改的原 checkpoint；没有改变 frozen hashes；用户说明要求中文；现有独立角色链和重试测试通过。

验证：增量 joint context、stage/verification coordination 测试、Ruff、生产文件 mypy 和 diff check。504 不能仅由输入大小推断；真实调用仍需验证。

存量处置：尚未批准的新需求正式删除当前 draft（保留 Product dialogue 和失败 Operation）；目标仓库 ff 到本次修复，新建同样需求，重新讨论并审批，不修改旧冻结输入或重置计数。已关闭的旧 K1 继续保留。

回滚：revert 本次平台提交，在空闲时重启；保留全部需求/Task/Operation/审批/worktree。
