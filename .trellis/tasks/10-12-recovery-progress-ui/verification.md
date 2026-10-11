# 增量验证与存量处置

## 实现结果

- 摘要需求历史复用 currentOperationProgress、recordedOperationOutcome；current progress 纳入 keyed row
  签名，恢复准备/最近准备事实及 Task-only 实现→测试→评审更新可见。
- SUCCEEDED 命令中性“命令已完成”，当次 BLOCKED/WAITING/DONE/CLOSED/PLANNING 单独封存结果标题。
- read-only recovery predicate 不依赖 Team read issue 非空或可写门，但只读成功的当前摘要 digest 所绑定
  完整来源、当前联合 Request checkpoint、精确计划。未就绪运行时/详情门不会恢复控制。
- retained changed page / active digest 漂移不附当前进展；新失败、等待、真实角色、过期 claim 保持优先级。
- 独立 review 复现了单作用域已读取新的完成结果被另一个旧 scope 的 RUNNING 摘要覆盖。局部恢复阅读
  predicate 比较所有有界当前 Team 页中同 ID 的 status/sequence/digest及精确 Project，active 与 prepared
  完整来源均检查；不修改共享 operationReadingRecords 或审批/POST 门。冲突解除可自动恢复只读展示。
- 共同 active-summary 门位于 platformProcessing 的两条展示分支之前，不受 canControl=true 短路。
  普通 Continue 不增加计划批准字段；精确恢复的 prepared/full/checkpoint 检查仅属于原专门阅读判定。

## Red / Green

基线 50bc91c 上初次新 fixture 8 cases 得到 7 failed / 1 passed（135.8 ms）。其中 UNKNOWN 负例失败是
fixture 预期写“已阻塞”，实际既有“等待工程处理”正确，已修正预期；6 个真实红例覆盖当前摘要内容缺失、
封存结果缺失、runtime/detail 门耦合以及当前角色标题缺失。首修后的 successor 负例缺少真实
source_delivery_id，按既有 currentRequestTasks 合同补充真实 lineage 后通过；未为 fixture 放宽代码。
新增 retained/digest-drift 历史页负例后 9 passed（176.8 ms）。
review 发现的单 scope 冲突通过真实摘要 GET 红例确认（1 failed / 66.7 ms）；新增双读取顺序、单 scope
两方向、active status/sequence/digest 和 prepared digest 的 16 组合，以及同页 items/active 冲突与
一致重读恢复负例后，最终新文件为 11 cases。
继续将 active-summary 一致性放到共同门：公开需求详情关闭后的真实列表可控态有 1 failed、
runtime 不可控态 1 passed（94.6 ms）。修后共同门两条负例通过；另增普通 Continue 无 approved-plan
正例并单独通过（60.7 ms）。当前新文件共 14 cases。
root 进一步指出 Team-wide 页也参与既有 merger；公开 Team-wide 首读→Project/Requirement 首读→
仅 Team-wide 更新完成结果得到 1 failed（65.9 ms）。helper 纳入所有当前 Team 页、逐项检查精确 Project，
相关新增 6 cases passed（86.5 ms），不改变缓存预算。当前新文件共 15 cases。

```sh
node --test tests/team_view/recovery-progress-summary.test.cjs \
  tests/team_view/operation-summary-reading.test.cjs \
  tests/team_view/operation-progress.test.cjs \
  tests/team_view/preparation-progress.test.cjs \
  tests/team_view/delivery-status.test.cjs
```

最终 Team-wide 修正后的上述 5 文件增量（`--test-reporter=dot`）：77 个通过标记、exit 0，命令耗时
0.191 s；包括新 15 cases。之前 71/73/75、新 9/11/13 的验证历史仍成立，重叠验证不能相加为独立覆盖。
`node --check src/ai_software_engineer/team_view/app.js`、
`node --check tests/team_view/recovery-progress-summary.test.cjs` 与 `git diff --check` 通过。
未跑全量、Python/SQL/模型/浏览器或操作生产；没有 npm/pnpm 前端项目配置，
直接用 Node 验证实际交付 JS。线上视觉验收和空闲受控上线由根任务后续完成。

## 存量数据处置

纯读侧错误，无 Schema/API/SQL/Task/approval 变更，无需改库或重建原 K1。所有 sealed Operation、
失败/停止/预算、草稿和审批保持原样。平台真实空闲后受控加载兼容资产，刷新原 Requirement 重读即可。
不可因展示恢复为“处理恢复”再次批准或启动工作；当前控制门仍严格检查完整当前事实。

## 风险与回滚

尚未线上手工验证布局；本改动仅增加现有行的当前说明和历史结果标题。摘要活跃集合超过首历史页时仍
由当前需求流程显示执行，该页没有行也不会伪造历史行。回滚此提交前端/test/spec并刷新，保留后端摘要接口
和全部持久化事实，不停止正在执行的角色。

## 独立复核

独立 reviewer `/root/native_truncated_diagnosis` 只读审实现与合同，初始新 9 cases 独立
9 passed（126.9 ms）；后增跨 scope、同页冲突、可控/不可控与普通 Continue 共 5 cases 独立
5 passed（112.2 ms）。这些是最终 77 内的重叠子集，不能叠加覆盖。
最后唯一 Team-wide case 独立 1 passed（69.6 ms）。新 15 = 原 9 + 后 5 + 最后 1，不与 77 相加。
root 和 reviewer 同时核对最终实现/spec/PRD/verification，无剩余代码阻塞。
