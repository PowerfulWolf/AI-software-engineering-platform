# 实施记录

基线 0cd980b；单 Agent、当前 checkout；只执行增量测试。
先复现真实入口，再实现 typed 计划/授权/派发/恢复/Console，最后进行跨层质量检查。

## 已完成

- 新增 PreExecutionRestartPlan、私有不可变 store、初始失败只读判定和精确授权。
- 使用既有 MySQL continuation fence 创建新 Task；先接回 native journal 再执行。
- 保留原批准链、原基线、冻结父上下文、旧 Task/事件；不制造 Coder 身份或候选。
- 同步 Console/联合需求审批、新 allocation ancestry、重启上下文读取和 Team read-side。
- 新 Task 的评估不计为额外自主成功样本；原失败记录不变。
- 正常、派发后/挂接后中断以及后续 Coder/QA 失败五条原生路径通过。

## 验证与回滚

详见 verification.md；生产只读检查，无真实模型调用、服务重启或需求审批。
仓库无模板镜像目录，规范以 .trellis/spec/core/delivery-recovery.md 为准。
