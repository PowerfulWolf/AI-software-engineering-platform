# 知识准备时限处理的前端闭环

## 问题

core 新增 RETRY_KNOWLEDGE_PREPARATION 与两类 missing proof 后，前端仍把它们视作
未知枚举。人工决定按钮因此消失，自动决定未被识别，当前原因、完整历史和复制报告缺少窗口
及工作额度说明。用户无法完成原需求的合法下一步。

## 范围

只修改 app.js、engineering-wait DOM 增量、新 frontend spec 与本任务目录。不改 core/domain/
Schema/生产数据，不运行 MySQL 或全量测试。多人共享代码库，保留其他人的改动。root 负责
生产平台操作和独立 review；Python engineering_history 的 evidence 贯通由 root 处理。

## 验收

- 产品处理入口、人工精确决定与自动授权记录中文且可理解。
- 时限、冻结上限、扩窗次数和一次剩余工作额度直接显示，后续独立 QA/Review 明确。
- 保留原 scope/checkpoint/proof、主体、服务能力与读新鲜度门禁；失效闭包不可提交。
- 新 missing 显示处理方和下一步，工作/窗口耗尽不广告必败执行。
- 当前、完整 Operation/Task 历史和复制报告共用文案，不变更原事实。
- 只跑相关 DOM、JS syntax 与 diff check。

## 回滚

一并撤回窗口决定展示与入口，保留新 typed 事实的 reader 和原审计记录。无数据库迁移，也不
创建替代需求。更新运行服务并刷新现存原需求即可读取新的展示。
