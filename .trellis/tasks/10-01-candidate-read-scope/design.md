# 完整差异审查输入

独立审查后采用明确版本的diff阅读模式，不新增MCP/通用shell，不增大预算。
Git完整base→candidate diff（所有hunks、上下文5行）承载新增文件完整内容和删除事实；
所有changed paths库存记录base/candidate blob/SHA、呈现方式、是否全文可见。
修改文件不冒称已读未变化部分。计划明确相关但未变化的文件全文必需；Context原有
required规范/需求/artifact继续完整。差异或依赖不足时只能NOT_TESTED/知识门。

真实K1测量：完整diff192,889 bytes，按当前估算47,537 tokens；未变的计划相关文件为
learning-proposal.schema.json 4,679bytes及work_queue/execution_store.py 18,294bytes。
比818KB完整文件更适合既有128k预算，最终仍必须连同Context、包装、receipt核算。

新增CandidateReadScope为内部typed输入，从ContextResolver读出的原Task section（typed
Task JSON，不解析模型prompt）和schema/hash-valid Plan/Implementation构造；匹配
task_id、plan.source_revision==Task.base_ref、parent、candidate/commit、artifact SHA。
Scope携带Task denied_paths；源读取复用WorkspacePolicy。生产factory持有resolver，可
注入BoundCandidateSource而不更改AgentRequest wire；normal与独立verification都复用。
Manager coordinate直接从source.runtime.task及封存artifact构造同一scope。

最终输入使用既有Context预算估算方法，连同所有序列化/包装成本检查，不截断、不自动扩容。
二进制/非regular required来源或真正必需输入超限明确拒绝；不读dirty/untracked文件，
不跟随symlink、不做lazy fetch。旧无typed上下文的低层adapter保留原保守全仓模式，
生产必须走typed绑定。测试必须验证factory接线，不只验证独立helper。

本源码包不代表QA verdict或环境能力。当前候选仍需独立受控MySQL增量receipt及QA/Review。
