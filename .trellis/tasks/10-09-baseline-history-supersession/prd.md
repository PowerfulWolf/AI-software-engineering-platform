# 连续基线更新的历史产物撤销链

目标：修复用户在同一 K1 需求先救援保留进度并暂停，再更新代码基线并暂停，最后点击继续原需求时遭遇的 `new progress does not match the bound execution source`。

范围：从完整、可信、已校验的基线绑定链累计精确撤销 ID；各运行输入、工作区准入、队列校验和候选交接共享此判断。只在选择当前产物时排除精确撤销的 ID，完整历史仍用于父级/替代图排序和审计。新增进度版本不一致仍必须拒绝，并显示中文原因。

验收：两次 PAUSE 更新之间没有 Coder 执行，旧 checkpoint 留在 store 时仍可明确继续；真实新 checkpoint 仍有效；未被精确撤销的错误源版本、跨 Task 和损坏绑定链必须拒绝；旧候选不得复活。公共 Host 流程保持原 Requirement/Task/branch/worktree、预算与独立 QA/Review，同候选 SHA 验收。

存量数据处置：不修改生产 SQL、已存 artifact/binding/Operation bytes、审批或现场；失败发生在 collect 阶段，应核对继续授权/队列未释放。修复加载后用户刷新原需求，重新明确点击最新绑定的继续入口即可，不重做计划、不新建需求。

验证：仅运行相关 Python 合同/公共恢复流程、JS 展示回归、Ruff、mypy；全量测试交给用户。无生产 POST、服务重启或需求执行。

回滚点：53d0eb4。无 wire/schema 或存量数据变更；空闲时可回退代码，但旧缺陷会恢复。现有绑定/审批历史始终保留。
