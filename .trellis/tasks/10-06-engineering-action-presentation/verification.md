# 工程处理交互展示验证

## 实现与复核

当前调查/处理由外层 details 改为 keyed 可见 section，位于需求“当前进展”。
调查按钮、结果/缺项和当前服务允许的决定不再需要展开；身份/hash 只保留内层折叠。
基线更新在无计划时是次级可选折叠，有当前未执行计划时直接展示计划与决定区域。
字段/按钮统一 14px、输入 40px 高、表单 gap12px、按钮可换行且 gap8px。

只读研究发现原 SHA 输入父容器没有 keyed block，相关轮询可能清空草稿。
表单现用 [bound, plan, canControlCurrentTeam()] 精确签名保留 DOM；无关事实更新保留
输入/值/焦点，精确计划、checkpoint 或门禁改变时替换旧控件，原提交前校验保持。

独立 reviewer 检查实现、样式和工程契约，无未解决问题；测试由独立代理更新并运行。
未新增 h2，四章归属保持；不自动调用调查/批准/继续，不把操作成功当作 WAITING 已解除。

## 增量验证

```sh
node --check src/ai_software_engineer/team_view/app.js
git diff --check
node --test tests/team_view/engineering-wait.test.cjs tests/team_view/ui.test.cjs \
  tests/team_view/delivery-status.test.cjs
NODE_PATH=/path/to/node_modules node --test tests/team_view/browser/engineering-wait.test.cjs \
  tests/team_view/browser/requirement-detail.test.cjs
```

- 轻量 34/34 通过。原权限/proof/plan/stale facts/QA 阶段边界检查均保留。
  轻量 fake DOM 补齐标准 classList.add 支持，未为 mock 改变产品逻辑。
- 隔离 Chrome 6/6 通过。390/1024/1440 下字段与按钮统一字号、间距足够、无溢出。
  调查缺项和决定默认可见；身份绑定折叠；精确未执行计划直接展示。
- SHA 草稿在无关 title/activity 更新后保留同一 form/input、值、焦点及可选展开状态；
  新计划使旧草稿控件替换。默认渲染/阅读/编辑/布局检查产生非 GET 请求为 0。
- 另用隔离 fixture 目视检查 1440/390 × 无计划表单/未执行计划共 4 份截图，卡片边界、
  字号、按钮和换行正确。为避开本机 Chrome headless 截图尺寸问题使用足够大的原生窗口。
  截图 fixture 只修改内存 facts，业务 HTTP 全部由 fixture 拦截，写请求为 0。
- 本机服务的 app.js/style.css 只读 GET 为 200、no-store，字节摘要与本轮工作区一致。
- 没有跑全量测试，没有请求生产业务 API、读取凭证或操作真实数据库/交付。

## 存量数据处置与回滚

仅前端展示与读状态 DOM 保留，无 Schema/API/数据库变更。现有需求的 WAITING、proof、
计划、审批及历史仍由原持久化事实提供，无需改库；刷新页面加载新资产后由用户操作。
已提交的旧决定不会被自动重复消费，当前工程绑定变化仍需重新调查或提出精确计划。

回滚本轮 app.js/style.css 并刷新即可恢复原展示，无需数据库回滚或重启执行中的角色。
阅读草稿保留仅在同一浏览器视图内生效，整页刷新仍开启新视图。
