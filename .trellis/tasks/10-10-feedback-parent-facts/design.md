# 精确输入事实替代推测反馈

## 根因与事实边界

首轮合法implementation-report父列表只有plan（tests/domain/factories.py与orchestration
test_runner已有真实契约fixture）。原UI把任意非空父列表当成收到QA/Review反馈，真实app.js
VM在仅art_plan_001输入时复现了这个误报。Artifact lineage证明引用关系，父ID的存在和名字
均不能证明父产物类型；引用输入也不是实现完成或验收通过。

## 实现范围

只修改appendExecutionArtifactDetails尾部反馈说明。生产调用来自当前Task详情里的完整
execution_history（legacy回退timeline）；从当前selected Task、当前Project唯一视图查该
history，不扫描其他Task或解析redacted DocumentView原JSON。ProductionTeamReader已校验
ArtifactStore、接纳receipt/claim，projector投影exact ID/URI/SHA/kind，这些已有字段足够。

当前entry须在该history中唯一且同对象，kind=artifact，URI=artifact://id，source_sha256合法
且等于details.artifact_sha256，task_id属于current Task或明确history_task_ids。每个父ID须
唯一并满足同样的已验证历史绑定；全部父条目可核对后才根据typedkind判断QA/Review输入。
重复、冲突、缺失和跨lineage身份均保持未知，不给模糊名字赋予类型。

有QA/Review父时说明已接收反馈输入，使用muted并说明问题仍须后续独立QA/Review验收；仅
plan/进度/普通输入只说输入已记录，未完全核对时中性说明当前历史不足以确认反馈。没有说
收到驳回，因为是否FAIL/REJECT属于独立报告结论；没有说已完成修改、已修复或已通过。

## Fixture与存量

既有browser正向fixture修正artifact URI/SHA，第一条替为plan产物并让Coder精确引用该plan
与历史QA父，保留12条总数和所有正向行为断言。implementation工程详情用唯一修改文件记录
定位，不依赖全局details索引。任务历史、产物、候选、状态和审批bytes均不改变。

无需数据迁移。完整旧报告加载新版后只重新计算说明；缺少绑定的legacy记录保留unknown，
不补造父产物、验收或接纳事实。回滚本函数本次展示分支并受控部署即可。
