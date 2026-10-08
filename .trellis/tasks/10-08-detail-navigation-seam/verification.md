# 需求详情导航衔接

## 修复与原因

桌面需求详情自身有 20px 滚动内边距，章节导航的 sticky top:0 留在内容区起点，因此吸顶时
上方和两侧会透出正在滚走的旧内容。使用容器与导航共用的 `--detail-panel-padding`，在
1180px 以上 requests 页面内部滚动时抵消导航顶部/左右偏移，保留按钮原有内边距和焦点空间。
1024px/390px 的页面滚动仍使用 top:0；任务弹窗工具栏已经贴顶，不需更改。

## 验证

```sh
NODE_PATH=/Users/zhangjunshuai/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules ASE_UI_SCREENSHOT_DIR=/tmp/ase-detail-nav-seam-20261008/after node --test tests/team_view/browser/requirement-detail.test.cjs tests/team_view/browser/task-detail-reading.test.cjs
git diff --check
```

- 现有浏览器增量检查：8 passed。未新增低影响样式的单元测试，未运行全量测试。
- 隔离 fixture 额外几何核验：1440px 时 nav.top 与详情内边框 top 均为 7.015625px，
  nav.left 与内边框 left 相同，右侧差 0.17px；无横向溢出。
- 1024px/390px 时 nav.top 均为 0，详情跟随页面滚动，按钮与章节标题完整可见。
- 已人工检查修复前后的桌面和手机截图：旧内容不再从桌面导航顶部或侧边露出；正常内边距
  和窄屏双行导航保留。截图位于 `/tmp/ase-detail-nav-seam-20261008/{before,after}`。
- 独立只读复核无 must-fix；需求内滚动/页面滚动断点及任务弹窗作用域正确。

## 生效方式

生产 `web_console/transport.py::create_console_app` 在启动时缓存 style.css 字节，请求仅返回
缓存内容。用户需在服务空闲时运行 `./scripts/ase-console-service.sh restart`，再刷新浏览器。
响应已有 no-store，普通刷新即可。旧只读 Team Server 每请求读文件的方式不适用于生产 Console。

## 存量数据处置 / 回滚

仅前端 CSS 和规范/任务说明变化，无 Schema/API/状态迁移。未执行任何生产 ASE 操作，
无需改库或处理既有需求、Task、Operation、审批、队列。回滚 CSS 后在空闲时重新加载服务
资产并刷新即可；本任务没有替用户重启服务。
