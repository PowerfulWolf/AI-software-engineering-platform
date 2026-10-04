# 实现与验证

- 按完整路径保留语法检查，删除 basename→既有文件位置的推断；更新原错误测试，增加五种合法同名文件与六种非法路径的真实 DesignerService 回归。
- 给生产 guard 增加已知静态拒绝原因的中文映射；未知异常正文不回显。读侧和 DOM 对旧类名提示做只读中文展示。
- 改前 `pytest -q tests/design/test_service.py -k same_basename`：5 failed，复现生产同名误报。改后相关三文件：50 passed；Node DOM harness：6 passed。生产三文件 mypy 通过，未跑全量。
- 生产只读重放：当前需求的 frozen profile/DerivedStageInputs 曾在 _validate_affected_paths 拒绝 ports.py、models.py、store.py、audit.py、service.py、execution.py、docs/architecture/contracts.md；修复后应再次核验，正式恢复以 ASE 事件为准。

## 存量数据处置

目标父需求 delivery_multi_74df2af872dd99c7b3369341c6a663c707aebb97，原生子交付 delivery_da6d0347b14c9ab6d9fd1a6bf0b74dbf，DESIGNING 阶段失败、尚无 Task。保留原始批准设计/计划和失败 checkpoint。服务空闲时部署，使用正式 Continue 重试未完成阶段，不直接改库。代码基线升级及 .trellis 维护责任不能被此修复默默批准，后续按精确恢复/知识确认流程处理。

回滚：revert 本修复提交，在空闲时重启；不用回滚或删除 durable records。
