# Design

## Project resolution

`TeamHost._resolve_project_id` 已能通过 Requirement/Delivery sidecar 查找唯一 Project。新增带 `delivery_id` 的公开入口，CLI 的 status 选择 native/joint service 后传入该标识；多匹配继续拒绝并返回稳定中文错误。

## Drift diagnosis

准备事实与 checkpoint 的 preparation digest 不一致时，拒绝所有会推进交付的操作。只读查询保留历史 checkpoint，并返回诊断；诊断不写 journal。执行入口继续使用 typed `CHECKPOINT_DRIFT`/恢复门禁，必须基于当前 preparation 产生新的精确计划。

## Blocker presentation

在 `team_view.blocker_text` 增加稳定消息映射和结构化原因分类。只复制安全的 run ID、evidence digest、candidate SHA 等不透明标识，不回显模型响应、路径秘密或完整 provider body。未知消息保留原始安全摘要，避免误称 PASS。

## Read-side precedence

继续使用 durable StateEvent、Evaluation、Artifact、Assignment、Lease、Handoff 重算 projection。活动 successor 和当前角色运行事实优先于旧 Manager advice；终态 Task 保留 blocker，不能展示为“开发中”。
