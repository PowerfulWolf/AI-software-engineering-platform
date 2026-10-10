# Header 徽标增量验证

## 根因与修复

root 部署复核发现 Node 当前状态和 Presentation 已正确，但完整 badge 把 `deliveryPhase`
从 durable BLOCKED 回退的旧阶段拼到当前 label 前面。此前只核对 node/status/flow，漏掉了
最终组合后的完整徽标文本。恢复中的历史终态应保留，不能当当前状态的阶段前缀。

`requestNodeBadge` 仅对 currentApproval/platformProcessing 直接使用 node.label，其他状态仍
按真实 phase + label 展示，保留 node.state 的原样式。没有更改流程、权限、其他布局或事实。
新增失败模式已补入 web-console spec：跨 helper 的最终 UI 文本必须做完整断言。

## RED → GREEN

真实 STOPPED + terminal BLOCKED fixture 的两条完整badge断言首先失败：

- `已阻塞 · 待工程确认` 不等于 `待工程确认`。
- `已阻塞 · 平台正在处理恢复` 不等于 `平台正在处理恢复`。

修复后两条窄case通过。已有 fresh READY/RUNNING case补完整 `实现 · 已排队/执行中` 断言；
平台处理后真实新child failure补仍显示已阻塞断言，保持当前真实执行和新阻塞语义。

命令：

```sh
node --test --test-reporter=spec --test-name-pattern='a current exact recovery decision|a new platform recovery operation' tests/team_view/engineering-wait.test.cjs
node --test --test-reporter=dot tests/team_view/engineering-wait.test.cjs tests/team_view/product-execution.test.cjs tests/team_view/historical-child.test.cjs
node --check src/ai_software_engineer/team_view/app.js
git diff --check
```

结果：窄case **2 passed**；受影响三文件最终一次 **94 passed，0 failed**，约0.23秒；syntax、
whitespace通过。没有全量测试。

## 独立复核

`/root/coder_python_tooling_fix` 窄只读review通过，无阻断。核对只有currentApproval/
platformProcessing显示当前label；真实role仍保留phase、new failure仍blocked，样式仍取
node.state，API/提交门/权限/历史不改。独立执行两条badge case：**2 passed，55.1 ms**；静态
确认fresh READY/RUNNING断言保持“实现 · 已排队/执行中”。

## 存量数据处置、风险与回滚

无需改库：原Requirement/Task终态和恢复计划都是合法事实，本次仅修最终badge文本。没有
生产GET、审批、服务操作、数据写入或提交。未做浏览器视觉验收。root统一部署后，在原K1
查看当前新鲜方案的完整badge及当前决定，并以重新准备的精确方案走公开审批即可。

风险仅限这两类当前恢复状态不再在badge展示历史阶段，真实阶段事实仍在具体模块。回滚只
撤销requestNodeBadge的本次拼接分支并受控部署，无需重建需求、恢复数据库或修改原计划。
