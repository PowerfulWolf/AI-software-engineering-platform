# T026 PRD：事件驱动 RunProjection 与只读 read API

目标：从 durable StateEvent、Evaluation、Artifact、Evidence、Assignment、Lease 和 Handoff
事实重算 Task/Run/Agent/Lease timeline。验收：重复构建稳定、冲突 fail closed、schema-valid，
read API 只支持 GET、过滤/分页和详情，不写状态或 verdict。
