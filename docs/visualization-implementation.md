# T027：本地 Agent 工作可视化实现

T027 在 T026 `ProjectionSnapshot` / `ReadOnlyProjectionApi` 之上提供一个无依赖、可离线打开的
只读 dashboard renderer。入口是 `DashboardRenderer`：

```python
from ai_software_engineer.visualization import DashboardRenderer

html = DashboardRenderer().render_html(snapshot)
json_payload = DashboardRenderer().render_json(read_api)
```

## 四个视图

- Task board：delivery/scheduling status、attempt、candidate、QA/Review 和 artifact/evidence IDs；
- Run timeline：State、Evaluation、Artifact、Evidence、Assignment、Lease、Handoff 按时间排序，保留 URI/digest；
- Agent capacity/detail：角色、模型、Run/Lease 引用，只统计 projection 中的 ACTIVE lease；总容量未知时显式 `capacity_known=false`；
- Human inbox：从 `WAITING_HUMAN` WorkItem 或 `BLOCKED` Task 推导，保留 reason/evidence/handoff 引用。

Renderer 不持有 repository、SQLite、subprocess 或 Agent adapter，不能写 Task、verdict、artifact
或状态。HTML 使用 escaped JSON 和浏览器 `textContent`，目标仓库文本不能结束 script 标签。

v0.1 采用静态 HTML，不引入前端构建链、WebSocket、消息队列或向量库；人工决策仍属于 Human
boundary，不属于 dashboard。
