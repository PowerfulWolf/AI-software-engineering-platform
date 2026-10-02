# 候选验证阅读范围

## 真实问题

K1候选 bd40ce051cf8f0fcc70009f493d8fd2cba32d833 已被原生状态机接纳，Coder Run
run_c1904be3d59e4e448bb924b3b32bfff6 成功。QA Run run_7f3ccd4e2c95439cb33fbacb4af29914
尚未调用模型即被 candidate_read_snapshot 的2MB全仓预算拒绝，Task进入BLOCKED。
父Operation operation_bcdbe757d0b507896544852e8efc0634随后因Manager协调额度耗尽失败。

只读Git计数：1,411 regular blobs /10,234,712 bytes；20个变更文件/818,399 bytes。
根因是把全部read_paths授权视为本次必需输入。另查到helper没有传Task.denied_paths。

## 目标与不可放宽边界

从可信原Task基线、已验证plan/implementation和实际base→candidate Git变化构建有界候选
阅读范围。不靠Coder自报paths，不用candidate^遗漏早期attempt，不自动提高2MB上限、
不截断必需代码、不启用通用shell。不把读权限范围当依赖闭包。源文件版本/Blob/hash/选择
理由可核对；未阅读部分须明确列为范围之外，缺依赖不能PASS。

需要明确核算最终prompt预算：现有源码在ContextBundle编译后追加，字节上限并不等于
128k生产输入预算。全20文件约818KB，以既有4chars/token估算也可能超限，不能只替换
文件列表就声称能完成恢复。设计需收敛完整变更视图、必需依赖与缺失上下文处理。

## 范围

agents/codex_policy.py及新typed source-scope模块、Codex CLI adapter、生产factory/
backend、独立verification entry、相关tests、verification-environment规范和必要文档。
保持普通交付、独立QA/Reviewer与Manager coordination三处同一读取契约。

验收：大无关文件不耗尽精确范围；必需范围超限稳定拒绝；完整变化库存及多提交/删除/
重命名明确；denied路径、symlink、binary、错误artifact/Task/revision拒绝或明确未验；
不读dirty/untracked宿主数据；Git禁止lazy-fetch。真实factory/adapter离线fixture先RED，
只跑增量，独立QA/Reviewer。不得以本平台测试冒充K1候选QA verdict。

## 存量与回滚

保留当前Task、候选、原失败和全部审批。修复后仅通过原生候选验证恢复生成新的精确计划，
不再跑Coder、不重置Manager/Task额度。MySQL前提由10-01-python-mysql-verification处理。
当前代码基线3e8e90f；回滚保留sidecar事实。不得直接改库或删除已消耗的invocation。
