# 增量验证

## Red

在改生产代码前，新增上游 UNKNOWN + RUNNING、静态队列/重试/等待、产品确认与 DONE/CLOSED
矩阵以及真实 Chrome 用例。轻量新增 3 项在旧版因缺少共享节点派生失败；Chrome 在
DESIGNING + UNKNOWN + PRODUCT_APPROVAL RUNNING 场景观察已通过产品节点仍为蓝色，
绿色断言失败。该 fixture 随后验证当前设计节点蓝色与其他颜色、真实文本和原 UNKNOWN 保留。

独立 review 发现并纳入契约：VERIFY_* 空队列不得被父 INTEGRATING RUNNING 跳过；
QUEUED/CONTINUE_REQUIRED 残留 claim 不证明已恢复；预算与审批等原有细分等待保持；
最后一轮合法工作预留不因 attempts 触顶被单独染红。

## Green

```text
node --test tests/team_view/product-execution.test.cjs \
  tests/team_view/delivery-status.test.cjs tests/team_view/knowledge-gap.test.cjs
60 passed, 0 failed

node --test tests/team_view/ui.test.cjs
6 passed, 0 failed

NODE_PATH=/Users/zhangjunshuai/Library/Caches/ase-validation/node/node_modules \
  node --test tests/team_view/browser/product-execution.test.cjs
4 passed, 0 failed, no unhandled browser errors

node --check src/ai_software_engineer/team_view/app.js
git diff --check
passed
```

真实 computed style：通过节点 rgb(23,99,75) 绿色、执行节点 rgb(36,89,204) 蓝色、阻塞节点
rgb(198,40,40) 红色、排队节点 rgb(226,232,240) 灰色。当前节点文字/aria-current、原 API
execution UNKNOWN、工程详情、无 active 状态及 DONE 七节点完成均已验证。

最终定向回归确认卡片在三个角色均 RUNNING 的轮询中更新实现/测试/评审文字；旧 FAILED
Operation、旧 Manager advice 均不遮当前无 claim successor，包括 NEW/PLANNING。另一个
生产形状回归先在旧 guard 上复现失败：FAILED.result=null、inputOld→currentNew，阶段
attempt 已追加 checkpoint 后的 ProductApproval/Continue 真实失败必须红色；其他 Project
不建立本需求失败。该补齐只重跑相关轻量矩阵与语法/diff 检查。

上述为受影响前端增量文件，没有运行 Python/全仓全量测试，也没有生产 API 写操作、模型调用、
部署、commit 或 push。

## 存量处置与回滚

独立只读复核 `/root/node_status_check` 通过；最终合并运行相关轻量文件 66/66，真实
Chrome 4/4，语法与 diff 检查通过。复核包含跨角色同 RUNNING 状态轮询、当前 successor
抑制旧失败，以及 FAILED.result=null / 输入 checkpoint 落后于当前阶段的真实契约。

无需数据库迁移或改库，Task/Requirement/Operation、审批、预算、artifact、历史 bytes/hash
全部保留。只更新前端资产后刷新现有需求页面即可，无需重建需求或重复批准；进行中的服务
无需重启。回滚本次前端资产并刷新页面，不改变任何原始交付事实。
