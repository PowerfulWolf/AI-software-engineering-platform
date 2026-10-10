# 增量验证

原 HEAD delivery-status 用例在完整当前读取/控制 harness 后仍 RED：
`reaped lease keeps interruption and exact approval visible until a new claim` 期望
“等待审批 · 单次 Coder 续跑”，实际为“执行中断，等待恢复”。旧测试和断言保留。

GREEN：活动过滤只对已核验中断的 RETRY_SCHEDULED 作例外后原用例通过。新增一项包含
普通 provider retry、无关 wait reason、有效 claim、READY、有效/过期 LEASED/RUNNING 以及
Task QUEUED/CONTINUE_REQUIRED 的反向矩阵；全都不能重新显示旧审批或改变保存事实。

四个受影响文件的最终增量命令见同批 `10-10-recovery-read-contention-ux/verification.md`，
共 120 passed、0 failed；node --check 与 git diff --check 通过。未跑全量，无生产动作。
此问题与 Team 503 恢复观察分开登记。

## 独立审查

`baseline_resume_contract` 完成只读独立审查，未发现阻断问题。例外仅限已核验中断的
`RETRY_SCHEDULED`，后来的 READY/LEASED/RUNNING（含新 claim 再过期）与 Task
QUEUED/CONTINUE_REQUIRED 仍阻止旧审批复活。与同批读取展示修复共用的独立窄回归
11 passed、0 failed。无需迁移历史事实；等待生产操作安全收尾后部署并重算读侧。
