# 实现计划

1. 先用 public seam tests 固化 Evaluation event store 的 immutable replay 与 corruption 行为。
2. 逐 case 增加 `EvaluationEngine` tracer tests：eligible → pending → human/policy → aggregate。
3. 实现 TraceBuilder 对 Repository/ArtifactStore/EventStore 的身份与顺序校验。
4. 用 DONE/BLOCKED tests 驱动 HandoffBuilder，再实现 FileHandoffStore JSON + Markdown。
5. 增加至少 5 个合成 evaluation cases 与 JSON Schema contract fixtures。
6. 同步 README、docs/evaluation、contracts、architecture、Trellis core spec。
7. 运行全套质量门并记录 verification。
