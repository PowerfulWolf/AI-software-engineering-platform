# 进度

- 读侧已定位：active child 投影遗漏 coordination；Manager UI 无条件展示旧 advice。
- 已确认生产租约实际过期，Worker 续约根因正在独立检查。
- 计划验证：定向 Python projection tests、Node 状态 DOM tests、受影响 lease/recovery tests、实际 localhost 页面。禁止全量测试。

## 2026-10-01 验证

- 根因：pmset 实证空闲休眠74秒跨过60秒租约；保持过期owner拒绝，服务增加绑定子进程的 caffeinate -i。
- 恢复实现：精确新审批下同Task/同worktree一次新claim、新Run，严格验证seed和旧receipt，保留全部历史；Worker在runtime.run_step周围绑定真实execution guard。
- 独立 Reviewer 最终复核无阻断项。独立 QA 发现 reaper 后前端中断消失，现已修复并复核关闭：EXPIRED claim + exact lease wait reason + RETRY_SCHEDULED，直到新有效claim取代。
- 增量验证：Node delivery-status/ui 14 passed；Python active-child projection 2 passed；Worker supervisor/knowledge wait/heartbeat 7 passed（独立QA）；records 2 passed（独立QA）；服务生命周期与配置应用2 passed。
- 原生隔离MySQL/Git恢复测试前两次3 passed，均验证旧receipt保留、新Run、Coder→QA→Reviewer→DONE。补充只读dispatch查询及真实reaper投影断言后重新验证中。
- Ruff、受影响Mypy通过；不跑全量测试。
- 存量处理：生产Task/SQL未直接改写。当前服务应用新恢复能力前须安全重启，再通过Console生成/批准新interruption计划；最终业务交付状态待原生执行结果。
- 最新 native+records 增量：3 passed /155.05s，包括真实reaper后API仍投影执行中断。相关4文件Mypy通过。安全重启服务（无活动Operation），新PID 58046，自带防空闲休眠；已开始Console恢复提案。

## 生产恢复审计

- 提案 Operation：`operation_c9a36af1ce9bbf546db4dbd37dba4110`，SUCCEEDED。
- 精确 interruption plan：`fdf94c17179a94bdaa0bbd5ca88c2f22f2842555a96757262b96430d6ee89209`。
- 按用户既有授权提交审批 Operation：`operation_9f4216092a25320777164cf97825b756`。
- 浏览器实测审批前显示“执行中断”及“Manager 协调 · 等待审批 · 批准中断后的单次 Coder 续跑”，没有旧英文summary或伪“等待恢复审批”；截图 `/tmp/ase-k1-exact-interruption-approval.png`。
- 审批执行中原生reaper已将旧claim置EXPIRED、WorkItem置RETRY_SCHEDULED，API持续显示执行中断（不会冒充Coder已执行）。后续新claim和真实交付结果待观察。
- 生产新续跑已准入：`run_5f682ff459a7488ebeb07d95e21364e1`，`lease_88ba54474215642b2cf27cbe`，generation 1，04:32:08Z；原Task attempt仍为1。
- API新租约LEASE_VALID、Coder current_stage=true、QA/Reviewer=false；实际Chrome页面显示“进行中 / 实现中 / Manager 协调 · 处理中（继续交付）”，无执行中断、旧英文summary或旧待审批。截图 `/tmp/ase-k1-resumed-ui.png`。
- 05:02Z 真实Coder到达1800秒执行上限，保留新增改动但未输出candidate/progress，原生Task进入BLOCKED（POLICY_VIOLATION，cause=TIMEOUT）。租约全程有效，与休眠失租约不同。
- 审批Operation因后续Manager协调轮次耗尽返回FAILED；未提高/重置预算。原生继续入口仍能生成恢复计划。
- 新普通恢复计划 `66fbbc0a50aba8927d79156a6e66c81a022deb0631bca5c9497f763998867387` 精确引用本轮 `run_5f682ff459a7488ebeb07d95e21364e1` / `ctx_2577c18cc439840858c89a748af10c10c3b016d306990d9ddc6386b06eeffa63`，保留9文件（新增tests/specs/test_learning.py，已在原允许范围）。提案Operation `operation_a44ec74025e4e9fdb878af68625ddf2d` 成功，已按用户授权批准并继续。
- 后续审批 Operation `operation_24790fe61731e8df831d44c45d6f440f` 已启动新 Task `task_recovery_66fbbc0a50aba8927d79156a6e66c81a`；05:09Z API确认IMPLEMENTING、新Coder有效租约。旧Task BLOCKED未改写。
- 独立QA只读复查上一轮超时：route时长1806378ms，evaluation NOT_PRODUCED，无artifact；request明确1800s、prompt预留300s并要求focused tests/progress。context 26927/128000且未截断。无命令轨迹，不能断言全量测试/环境等待；现证据无法证实新的平台缺陷。保持原超时分类，不扩大预算或改写事实。
- 05:32Z 新Task持续有效心跳，当前diff显示生产接线、Console/API、增量测试和补采文档继续完善；尚无候选或QA/Review结论，Requirement只读投影DELIVERING且coordination=null。
- 05:37Z 新Task成功产出并接纳 `art_coder_7827e39b42647f7afece6b96cdd024af` coder-progress（Run `run_9560e8fb29d14e55926c31d71d16664f`）。17文件库存经平台校验，原生同Task进入attempt2，没有新增人工审批。
- Progress报告：相关Python31 passed、Node6 passed、Ruff/Mypy/format通过（是Coder报告，非QA verdict）；MySQL测试sandbox socket拒绝；旧contracts fixture需更新但tests/contracts/test_json_schema_contracts.py不在当前write allowlist。剩余工作由原生续跑处理，不由operator修改业务代码或扩权。
