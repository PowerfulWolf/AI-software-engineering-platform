# 可供人使用的中断进度恢复闭环

## 目标与范围

修复原 K1 需求的真实中断问题，同时保证用户能理解前端原因并执行可用下一步。
完整交付依赖已选择的 Team/Project 知识、exact Product 审批、设计/计划和独立 Coder/QA/Review。
维护者不能通过新建需求、直接改库、修改业务候选或伪造 verdict 绕过交付。

当前现场：第 7 轮 Coder 到达 30 分钟限制；原 start/stop 可校验，工作区保留，但完整源码
捕获因类型注解、运行时随机数生成及无效测试凭证被秘密字段正则拒绝，未生成 receipt。
HANDLE 误显示停止记录缺失；PLATFORM_ATTENTION 页面只有不执行 reconcile 的 INSPECT。

## 验收

- 正常 Python 类型注解和可证明不含凭证值的表达式可原样捕获、wire 重读与再次校验。
- 注解右侧的真实敏感字面量、带密钥默认值、遮蔽标准库、字符串/注释/未知语言仍拒绝。
- 已核验真实停止与完整进度封存为不同事实；封存失败不虚构执行活跃，也不授权继续。
- 失败报告只保存有限 typed 安全诊断，普通用户能看懂原因、处理方、下一步和复查时机。
- 修复后的同一原需求可通过显式 HANDLE 重新处理；不要求用户知道 lease/hash/内部路径。
- 保留旧 immutable wire/digest、审批、预算、独立 QA/Review 和全部历史。
- 增量测试覆盖 actual source → Git capture → persisted wire → verified recovery 和 UI 操作。

## 验证与回滚

只运行受影响的 pytest、Node UI 测试、ruff、mypy 与 Schema 校验，不运行全量测试。
部署需空闲受控重启。回滚代码也保留所有 append-only 记录，不删除草稿或重置 Task。
存量需求只通过公开 exact-bound Console 操作处理；若仍缺事实，记录明确且可行动的原因。
