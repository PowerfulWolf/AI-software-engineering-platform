# 实施记录

先以同步假事件驱动真实 `ProjectConsole._run`，记录请求等待值和模拟消耗时间，
建立持续空闲、submit唤醒、外部writer和stop/cancel恢复的红测。随后只修改局部等待逻辑，
增量复跑现有 core、idle replay 和 shutdown 门禁。

维护 worktree：`/Users/zhangjunshuai/workspace/code/ase-console-idle-backoff`。
主仓和注册仓文件、生产 HTTP/SQL/服务均不操作。并行开发者负责 summary API 和前端，
本任务不修改端点、store 或 shared spec index，避免交叉覆盖。
