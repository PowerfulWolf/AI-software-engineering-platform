# 增量验证与存量恢复

- Red：stage retry + 三 producer 投影选择，4 failed，缺少 stage_budget。真实服务第二次 producer 调用失败，非“测试仅比较字符串”。
- Green：`.venv/bin/pytest -q --tb=short tests/manager/test_stage_coordination.py tests/manager/test_joint_context_limits.py tests/knowledge/test_consultation.py tests/knowledge/test_gaps.py tests/knowledge/test_stages.py`，59 passed。三角色与最后一次已预留调用、600→1200、旧 Manager cursor 清除、冻结 source/审批不变、知识权限和 gap resolution 均覆盖。
- Ruff check/format、两个生产文件 mypy、diff check 通过。未运行全量。
- 现有 Designer/Planner 纠错增量：`.venv/bin/pytest -q --tb=short tests/manager/test_joint_designer_feedback.py tests/manager/test_joint_planner_feedback.py`，35 passed；非 Manager 的拒绝、剩余工作预算及修正路径保持。
- 当前新 K1 gap 的 answer、来源和批准经正式 Console knowledge-resolutions 接口保存，resolution_id=52429d8a8c8c85c32593db789bee382619826381118f8d7396bd85d08ad0487a。原 gap 和调用历史保留，无数据库修复或预算重置。
- 部署等待空闲；之后普通 Continue，真实新输入/后续交付仍需跟踪。浏览器不可用，不宣称视觉验收。
