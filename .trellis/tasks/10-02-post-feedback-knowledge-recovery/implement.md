# Implementation / verification

根因：回派IMPLEMENTING不是provider已执行的证明；旧恢复入口同时拒绝candidate与缺少failed
Coder run。新增gate在原有完整candidate provenance后重验真实未完成knowledge consultation、
原报告/成功Coder route、stopped worker和exact clean Git ownership，仅允许新verification计划。
独立Review发现adapter异常也可能被误标knowledge failed，已用sealed consultation-input/
complete absence/input SHA收紧，并通过adapter-entered无完成route的反例验证拒绝。

## 增量验证

- 真实Git/隔离MySQL post-feedback provider dirty 与 knowledge TIMEOUT 两场景：2 passed/32.28s。
- 升级为真实KnowledgeRunContextBuilder/ConsultationService（先封存input再故障）与
  adapter-entered StructuredModelError负向：2 passed/32.58s。
- AUTHENTICATION_ERROR真实知识故障与progress source关联：11 passed/17.64s。
- candidate verification、snapshot、sealed recovery verdict离线关联：47 passed/2.00s。
- 独立QA真实Git semantic branches：29 passed，snapshot 22 passed，knowledge composition11项。
  新版独立12项临时fixture覆盖QA/Review×TIMEOUT/AUTH、缺input/错误SHA/歧义、Review parent、
  completed consultation后adapter异常等拒绝。独立Review与新版独立QA均无阻塞finding；
  AUTH持久fixture已由root补入并通过，剩余input tamper/Review离线持久覆盖为低优先级建议。
  这些工程检查不构成K1原生verdict。
- Ruff check/format、strict Mypy四个变更模块、diff check通过；不跑全量pytest。
- 真实K1原生source只读回放：e41 candidate、d4 Task、BLOCKED checkpoint保持，零模型调用、
  零生产数据写入。未知reason、active worker、later provider、dirty/漂移/缺marker反向覆盖。

## 风险 / 回滚

只接受具有完整knowledge input/Context/receipt事实的窄范围旧任务；缺事实时继续fail closed。
读取只证明候选可提案，不能代替新精确审批或QA/Review。回滚提交并空闲重启；保留所有历史。

## 存量数据处置

保留 d4 Task、e41 candidate、原 QA FAIL、所有知识超时及拒绝Operation。加载修复后重新
提出exact32节点受控验证并审批；真实FAIL通过正常remediation给新基线Coder，不直接改库。
