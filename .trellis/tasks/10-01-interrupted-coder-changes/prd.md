# 中断后完整改动恢复

真实继续Operation `operation_a99db3b82fe9d27c3b60a320d2d1c448`失败于
`interruption.py:91 → GitWorktreeManager.verify_capture`：首轮恢复Coder从ed12f25基线
继续开发，服务中断前已有20文件合法改动；当前入口仅允许HEAD/index/content与最初seed
完全一致。真实工作区没有candidate、progress或completed route，旧claim已过期。

目标：在现有首轮、无输出、停止进程、失效租约边界内，允许**新精确批准**绑定当前完整
工作区快照，生成一次replacement Run。原始seed/invocation/Task/事件不改、不覆盖批准。

范围：interruption records/service、Schema生成器和产物、resume/Console审批说明、相关
增量测试与规范。禁止自动接受dirty drift、扩大write paths、重复使用旧审批或重置预算。

验收：合法改动发生在提案前可封存并独立批准；提案后任一文件、index、HEAD、身份变化拒绝；
旧无capture计划wire/digest/行为兼容；越权、非安全文件、已输出/已运行replacement仍拒绝。
真实Git/MySQL离线fixture保留原seed与invocation，新claim/Run下Coder→QA→Reviewer→DONE。
真实K1由同一入口审批续跑，最终业务验收不能由本平台fixture代替。

允许路径：recovery/interruption*.py、resume.py、entry.py、web_console/manager.py、对应tests、
scripts/generate-interruption-schema.py、schemas/recovery-interruption.schema.json、本任务及相关规范。
跨语言契约说明同步维护 docs/architecture/contracts.md。
基线be35741。验证只用增量；回滚保留新计划，旧版本不能消费扩展capture审批，禁止改库绕过。
