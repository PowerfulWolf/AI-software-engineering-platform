# 生产发布与存量 K1 继续记录

平台修复提交 `2dbd713`、静态契约同步提交 `19de30a` 已推送 main。部署 checkout 从
`794b7c4` fast-forward 到 `2dbd713`。重启前公开 Operation 列表 266 条均无 RUNNING/QUEUED；
可信 service 脚本重建 Host，PID 从 36237 变为 18723，Console delivery_ready=true。
没有读取/输出 runtime.env，也未中断执行中的需求。

## 已完成的存量处置

- 目标始终为 `delivery_multi_8a5103309c232515bcf733947d32830365dd02c6`。
- 最终只读 proof 核验 original checkpoint `cf43013b4bb61038a2d65b0e4b0f74bdbdf8297a26d73e9f01e42d67f5543be9`，
  项目 4401 文件前后 hash inventory 完全一致；没有制造证明或修改既有状态。
- 在 2026-10-05 14:41:06 UTC 通过公开 `/api/v1/operations` 提交普通
  `CONTINUE_DELIVERY`，idempotency key=`k1-20261005-design-verification-correction-01`。
- Operation=`operation_91237e0bd6126efa9cfc4b072020e925`，QUEUED→RUNNING；
  使用精确 old checkpoint，没有附加范围/执行审批。
- 只读再次核验：首个 successor=`9e82867931f06d5d0c4cfbe1c7e4db3b26ddfa74af4715e73f0a4eb0d88b6b76`，
  DESIGNING；原 Product/approval/scope/preparations 全部相同，旧 Design 保存为 feedback，
  当前 Design/Plan/children 清空，旧 child 和全部 25 条历史保留。
- 后续正常预留 Designer 第 3 次执行，当前 checkpoint=
  `d40ae29e2fe4c0c43ef39340a6e0effcf6cf33bf2e389985bb4f709cd3e38c4f`。
  首个 successor 预算完全未改变（design=2）；正常新预留后 design=3，旧两次 capacity timeout
  保持 2，没有退款或重置。
- 原 ProductSpec SHA=`dfa7786dac7103d451679b8f2a443a2997afb72caaf05222d6ec5e4466bf93dd`。

公开 API 和 typed read-only Journal 两方证明相同需求已进入设计修正；当前没有业务 Task，
尚未进入 Coder/QA/Review，因此这份记录不表示 K1 已交付。后续仍由 ASE 原生角色生成
新 Design→Plan→Task→候选→独立 QA/Review。没有手工修改业务代码/verdict、SQL、旧 journal、
审批或 retry counter；没有 merge 业务候选。

审计文件位于平台维护目录 `maintenance/k1-delivery-20261005/`，包括精确公开 intent、
Operation、readonly proof 和 `design-correction-successor-01.json`。

## 独立生产 UI 核验

2026-10-05 14:45:36→14:45:42 UTC 的 Chrome GET/HEAD-only 检查与自然 polling 前后
重验通过。新 Operation 标题为“当前阶段 · 技术设计 · 执行中”，原因、ASE 团队和下一步
可读。旧 Operation `operation_e7b4d3a74d90f80baf4354c31e41e85d` 的封存 BLOCKED 仍为红色
“操作已结束 · 当次交付已阻塞”，灰色“命令已完成”，未被新状态覆盖。两行排障详情默认
折叠，技术 ID 不进入可见正文。全部六条 API 请求均为 GET，写请求尝试、pageerror 和 API
失败均为零；独立 reviewer 已查看实际 current/sealed/full 截图。

维护证据 `audit-newcontinue-ui-reviewer-2026-10-05T14-45-16-054Z.json` 的 SHA-256 为
`eb462352be6fdb1d4eccb2f1b27f59e096a30a5bbf4fc0c7dea0d545974276a0`；同前缀三张截图已
保留，没有覆盖原 red/green 证据。当前公开调用记录已封存一次 Designer knowledge_intent
真实 `codex/gpt-6.1-sol` 调用成功；本记录不从 Operation RUNNING 推断所有模型调用已结束。

## 回滚

执行空闲时回退代码并重建 Host，保留本次新旧 journal 和审批。不要删除已追加 successor
或恢复旧 invalid 设计；支持该 successor 的 Host 版本是后续继续交付的最低要求。
