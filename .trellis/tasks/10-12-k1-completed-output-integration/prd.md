# 原 K1 报告拒绝后的受控接续集成

目标：在同一 Requirement/非终态 Task/原分支保留完整合法草稿，修复普通已停止 INVALID_OUTPUT 无可用接续入口、模型切片指导含糊和旧Operation摘要投影兼容问题，安全部署后继续独立交付。

范围：集成 slice_output_guidance、operation_result_scope_compat、unaccepted_coder_draft_resume 和 UI 专属任务的已独立审查提交；精确更新规范导航、增量联合验证、受控服务部署和公开原需求动作审计。源码更新通过同Task baseline计划，不能手工rebase Coder或改原SQL。

验收：

- 所有独立问题的红绿、Schema/类型/权限/工作额度与canonical旧bytes兼容通过。
- 新INVALID source/same-source公共Host→PAUSE→RESUME→新claim/Context→独立QA/Review离线nativefixture通过。
- 浏览器summary gate与新UI集成保留完整资源身份，旧child结果不借父scope审批。
- 真正空闲+受控stop后部署；验证readiness/原330历史摘要原需求/原failure可读。
- 原需求公开准备精确方案，审阅目标与完整规范，按已有工程委托PAUSE批准后独立RESUME。旧Task终态、原失败/计数/history保留。

验证只做相关增量；K1 DONE需要真实candidate+QA PASS+Review APPROVE+Handoff，不以维护commit或Operation成功代替。

回滚：受控stop，兼容新的typed reason/schema保留所有历史。新binding/计费已消费后优先forward fix；不得直接改库撤销或伪造历史结果。
