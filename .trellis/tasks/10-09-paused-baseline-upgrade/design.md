# 同一需求的暂停、工程输入更新与明确继续

保存合法进度不等于开始下一轮执行。工程确认封存PAUSE绑定后，队列在原Task锁/authority/Task行
屏障内持久写WAITING_HUMAN，明确继续精确绑定最新版本、工作项、现场和等待摘要。
源码更新保持原需求/Task/分支/工作区和已有预算预留，并且必须延续暂停。旧缺省字段不落盘，
保持历史记录bytes/hash。具体契约见 `.trellis/spec/core/execution-baseline.md`。

原生工程规范采用不可变Git原/目标正文版本。提案只含完整引用、增改删与摘要，完整脱敏正文
单独安全持久化；只读API提供精确变更的完整差异。人工独立确认规则摘要后才能采用。Prompt
与知识Context统一选择最后获批版本，包括新增和删除。原Profile/编译结构化规则/范围仍为
不可变原批准事实；native structured source变更拒绝静默更新，独立sidecar规则保持冻结。

继续先写授权，再SQLrelease，再同步Supervisor。授权已保存但SQL未提交时需新鲜核验；SQL已提交
但Host尚未启动时仅对同一仍未执行的READY快照重复启动，并重新核验文件/索引/本机停止前提。
已执行或进入后续等待的旧决定重放返回现状。Console旧checkpoint只在已有精确决定时允许此
内部重放，首次过时提交始终拒绝。

不采用手工rebase、重建Requirement、改Task.base_ref、恢复额度、替角色修改verdict或自动merge。
仅增量验证：真实Git保存/继承、隔离MySQL暂停/继续与崩溃、公共Host原生三角色验收、HTTP只读
规则审阅、真实Chrome交互。完成后单独记录存量数据处置，生产K1留给用户在新版确认。
