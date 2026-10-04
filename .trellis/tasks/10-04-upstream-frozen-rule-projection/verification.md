# 增量验证和恢复记录

- 原 `_produce` 三个 producer 回归均失败：payload 含约 741 KB 重复 native corpus；修复后 `test_joint_context_limits.py` 11 passed (5.60s)，含三种上游 producer、完整知识/角色链与重工场景。
- stage/verification Manager 协调 23 passed (0.65s)。四文件 Ruff check/format check、三个生产文件 mypy、git diff --check 通过。
- 真实 K1 checkpoint：原序列化 1,205,326 bytes，投影后 100,843 bytes；冻结来源正文仍 1,163,582 bytes。只是输入测量，不宣称已证明外部 504 根因。
- 两次未完成 Product 尝试真实存在（product_transient=2），不退款或改写。该草稿尚无 ProductSpec/Approval/Design/Task，通过 DELETE_REQUIREMENT 正式退出当前库存，历史保留；在新基线重新创建同样需求。
- 主模型仍 gpt-6.1-sol；Settings API 为 Product/Designer/Planner 绑定已注册 Astra 备用，QA/Review 将现有 Responses 备用排在 CLI 前，保留 5.6 和 CLI 路由及凭据引用。服务重载时无活动角色。
- 真实 Product/QA/Review 和浏览器界面验收尚未完成；本任务仍跟踪真实交付。回滚平台提交并在空闲时重启，保留所有已发布事实。
