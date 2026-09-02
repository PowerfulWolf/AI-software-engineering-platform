# T027 Design

`DashboardRenderer.build_data` 从不可变 `ProjectionSnapshot` 生成 task_board、run_timeline、
agents、human_inbox；timeline 按 `(occurred_at, id, kind)` 稳定排序。Agent capacity 只合计
ACTIVE lease，并以 `capacity_known=false` 标明总容量未知。HTML 内嵌 canonical JSON，JS 只使用
`textContent`，不提供状态、verdict、命令或 merge 操作。
