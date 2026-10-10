# 实现与增量验证

恢复审批的用户决定和批准按钮保持可见；technical_facts仅承载Task/基线/时间/摘要，空值不改变
旧Operation wire/hash。主事实解释保留进度、同一Requirement继续、独立QA/Review与环境隔离；
没有workspace_snapshot的历史方案不会显示已停止或完整现场已核验。

RecoveryPlan新增可选完整snapshot，绑定source/capture/scope并参与精确批准摘要。entry在
提案前收集可信证明，current facts在批准/执行时fresh重读并比较。原BLOCKED Task不重置。

已通过：Node product-execution+engineering-wait 74条；Python manager/scope/workspace plan
80条；Git capture/source/model/snapshot 72条；限定Ruff/format/strict Mypy。
独立审查由baseline_resume_contract和coder_python_tooling_fix完成，精确审批门禁无退化。

test_current旧fixture对齐真实semantic branch，并在Task创建时明确生成无现代capture-policy的
历史fixture；不伪造stop，不削弱新gate。其真实Git/MySQL授权/历史保存2条已通过。

生产原K1仅只读预演：epoch source有效、合法业务27文件、完整库存2283、源现场环境18项。
这不是计划批准或交付；现有Requirement仍BLOCKED，等待部署后公开入口重新准备并批准。
浏览器连接仍无法认证，尚未完成真实视觉与焦点验收。全量测试未运行。

## 独立复审补充修复：具体服务能力门禁

发现：控制状态可读但 supported_actions 未提供 CONTINUE_DELIVERY 时，恢复批准按钮仍可点击，
点击必被拒且误提示审批方案变化。真实 app.js VM 复现 supports=false、ready=true、disabled=false，
submitted=0。修复后共享 capability issue 同时驱动公开中文服务原因、禁用按钮和点击时二次检查；
原 Project/checkpoint/signature/control/active guards 保持，不提交未知能力操作或生成批准。

## 独立复审补充修复：未修改文件的范围申请文案

发现：coder_scope_request 明确申请尚未修改的文件，但阻塞卡片统一称文件已超出授权。修复后
按可信审批中的 scope request 区分申请未修改文件和历史越权改动，保持原始审计记录。

限定增量验证：三个新增回归先执行 RED，全部因上述真实缺陷失败；修复后含既有精确审批、
消耗和 detached callback guards 共9项通过。命令：

```text
node --test --test-name-pattern='unsupported recovery approvals|withdrawn recovery capability|scope approval distinguishes|current exact approval|exact technical approval|recovery approval keeps human|every exact approval|detached exact approval' tests/team_view/engineering-wait.test.cjs tests/team_view/product-execution.test.cjs
9 passed
```

无需存量数据写入。无生产 ASE 操作、审批、重启、提交或真实模型调用。独立复审交给
console_fixture_alignment；app.js/functions、tests和spec的本轮ownership随后释放。
