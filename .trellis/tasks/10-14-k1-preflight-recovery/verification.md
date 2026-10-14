# 修复验证与恢复记录

2026-10-14：主干基线 a81ace0，远端 main 已 fetch 核验一致。

- 最终针对性回归：202 passed, 4 skipped，见 /tmp/ase-k1-focused-final.txt。4 项 macOS 沙箱边界另行真实执行，runner suite 21 passed，见 /tmp/ase-k1-runner-boundary.txt。
- JSON Schema / Planner /嵌入契约：137 passed，见 /tmp/ase-k1-contracts.txt。
- ruff、mypy 修改范围通过。已有导入的 Optional failed_run_id 增加非空断言。
- 大范围基线恢复回归最初 129 passed, 5 failed：4 项需要显式旧版 preflight stop 夹具，1 项仅错误文字断言。适配后单独复跑并保留结果；不能将最初失败声明为全通过。
- 新的公开 production test 用隔离 MySQL 和 fake model runner 证明 Coder 已产出候选，QA 在缺能力时仍等待；它不是 K1 产品验收 verdict。

存量目标：delivery_multi_bb78e2316afca47d005384542f685174535b69db；Task task_c833c3235d0bb73adba67937d16ea66c。
原 source 5f38922cd5cb9f236170f7edbd0ccb6f0ba6194b。使用公开 Console 基线流程恢复，不改 SQL 或旧历史文件。
