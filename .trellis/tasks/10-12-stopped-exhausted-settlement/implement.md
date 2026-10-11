# 实施与验证

1. 先写真实 stopped/exhausted fixture 的 public HANDLE 回归，再实现 typed record/collector/transaction。
2. 覆盖重入、停止/结果/claim/现场与预算反例；MySQL 原子性与历史前缀；Schema 与旧wire。
3. 增量 Ruff/strict mypy/相关测试，独立review；无生产直接SQL。

## 已完成验证

- 原红测：HANDLE 后 Task 仍 IMPLEMENTING（1 failed）；修后6个行为/Schema/旧wire测试通过。
- delivery_wait + repair schema 首轮69 passed，生成顺序问题修正后相关23 passed。
- 真实MySQL结案/重放、queue写入故障原子回滚、SQL提交前拒绝不发布成功：3 passed。
- 独立编写的公开联合Host回归：1 passed，23.55s；同Requirement进入RECOVERY_APPROVAL_REQUIRED，未自动审批/重复Coder。
- Ruff、format、strict mypy（8个源/测试文件）、diffcheck通过；独立review发现公开报告发布顺序问题，修复并增加提交边界回归后复审无阻断。

## 存量处置与回滚

未直接修改生产数据。本提交部署后，原K1通过公开HANDLE精确结束已实际停止且普通预算耗尽的旧Task，再用原Requirement的正常恢复提案和精确批准继续。保持旧failure/attempt/claim/stop/历史字节以及全部草稿。已有新增记录后保留typed readers；不能删除历史或把旧Task复活。
