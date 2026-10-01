# Python / MySQL 受控增量验证

## 目标与证据

K1 Coder progress `art_coder_7827e39b42647f7afece6b96cdd024af` 已记录 MySQL 测试被 sandbox socket 拒绝。独立 QA 确认现有 CLI verifier 禁通用 shell，Responses 命令环境不注入测试 DSN，独立候选验证只有 Swift executor capability。必须增加原生受控验证能力，不能以跳过测试或 operator 手工 verdict 交付。

## 边界

- 只接受精确候选 SHA、角色、审批计划和有限 pytest node IDs；禁止全量 pytest。
- 复用 VerificationEvidenceProvider/精确审批/immutable execution receipt/独立 QA 与 Reviewer。
- 保持 Agent 无 shell、网络、凭证 ambient authority；测试源码只读、独立 scratch/cache；真实反向拒绝测试。
- DSN 仅由可信执行器为本次独立容器生成，不从宿主业务环境继承，不进入模型/计划/API/日志；数据库必须隔离且独占。
- 已查当前 ASE_TEST_MYSQL_DSN principal 同时有业务库权限，不能直接交给候选测试。需独立实例/最小权限 principal；不得修改现有业务 MySQL 或使用其清库操作。
- 当前业务 Coder 正在运行，不重启服务或改其冻结权限；新能力待产生精确候选后审批执行。

## 验收

1. 错误候选、未批准计划、路径/argv/DSN/数据库权限漂移全部拒绝。
2. 定向 pytest 使用候选源码和只读注册工具链；无越权写入、无任意网络、无密钥输出。
3. 成功和失败均封存命令 receipt，QA/Reviewer各自解释；命令成功不等于verdict。
4. 旧 Swift plans/receipts保持hash与读取兼容。
5. 只跑增量单元/contract/隔离 fixture 集成与真实 sandbox refusal 测试。
6. 存量通过新精确恢复计划继续，不改旧Task/报告/审批/数据库历史。

## 允许路径与回滚

manager/verification_environment相关新模块、recovery/verification_*与store相关验证、Console模型/摘要、对应schemas/scripts/tests/docs/Trellis规范。具体接口与节点选择先在design.md收敛，之后实施。回滚保留已有facts/receipts/独立测试基础设施，禁止删审计或还原旧终态Task。
