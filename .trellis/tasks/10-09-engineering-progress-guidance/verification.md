# 验证与交付

## 结果

- `node --check src/ai_software_engineer/team_view/app.js`：通过。前端为原生 JavaScript，无独立 TypeScript 类型检查入口。
- `node --test tests/team_view/engineering-wait.test.cjs`：44 项通过。
- `NODE_PATH=/private/tmp/ase-rescue-ui-test-deps/node_modules node --test tests/team_view/browser/engineering-wait.test.cjs tests/team_view/browser/legacy-rescue.test.cjs`：21 项通过。
- 补充同一 Operation 的处理状态变更断言后，以 `--test-name-pattern='approved preservation stays paused'` 重跑 legacy-rescue：1 项通过。首次补充用例使用不适用于暂停入口的 QA 阶段 fixture，后改为保留暂停契约的真实处理方变化；同步纠正预期中文状态名称。
- `git diff --check`：通过。
- 人工查看 1440px / 390px 隔离浏览器截图：状态标题、深蓝状态标识、当前操作和阶段清晰；无横向溢出；三项说明唯一编号，第二项完整保留。

仅执行上述增量验证，没有运行全量测试。浏览器拦截 API 使用 fixture，不连接生产审批或修改数据库。

## 契约与覆盖

覆盖 QUEUED → RUNNING → SUCCEEDED，操作名、当前处理状态、无关轮询的 DOM 保留、操作结束移除状态卡；不伪造心跳、进度百分比、预计完成时间或交付成功。

重复编号源于带手工序号的文本再次进入 OL，分号拆句又拆开第二步。显式步骤改为无编号数组，普通段落保留既有拆句行为。新增共享状态卡复用现有作用域和阶段派生，不扩展操作权限。

## 存量数据处置

无需改库、重建需求或重新批准；Task、Operation、历史与审批记录均未改动。Console 创建时冻结前端资产，维护者需在服务空闲时受控执行 `./scripts/ase-console-service.sh restart`，成功后刷新浏览器。仅刷新旧进程不能加载本次改动；本次没有重启生产服务或继续需求。

## 已知限制与回滚

执行中表示 Operation 正在处理，不保证模型仍在线；当前阶段仅使用已读取的事实。回滚本提交并受控重启 Console、刷新浏览器即可恢复旧展示，持久化事实不受影响。
