# 后续 Coder 超时与范围申请

真实 Operation `operation_d042a07975dc4d7769c2a4829b0e6a7f` 返回
`requested scope does not bind the accepted Coder progress`。Task 第六轮 progress
`art_coder_b10b7bc4c0e81300c69104d2ec890f8a` 已接纳，第七轮 timeout 没有 artifact。
范围入口仅检查最后失败 route 的 artifact，丢失可核验的前轮范围依据。

目标：终态恢复可用最新已接纳的同 Task Coder progress 提出必要文件的精确 scope。
失败 source 仍是真实最后失败 Run/Context，capture 必须包含实际完整旧改动；不能把旧
progress 当最新代码快照、退款、修改旧权限、跳过双审批或 QA/Review。

验收：前轮接纳后真实执行失败能发现 scope；未接纳、错 Run/Context/Task/revision、
伪造末尾引用、旧 progress 请求、缺少或损坏 sealed facts 均拒绝。无已接纳progress保留
原行为。当前业务仓库 main 已由用户授权快进至 `15de91c`，旧 worktree 保留。

允许路径：recovery/progress_source.py、native.py、对应定向测试、本任务及相关 spec。
验证：Ruff/Mypy、非 MySQL 定向测试、一个原生 Git/MySQL scope 恢复 fixture（需要时）。
回滚：回退代码，保留 Operation、旧 Task、scope/plan审批和 worktree；不改生产SQL。
