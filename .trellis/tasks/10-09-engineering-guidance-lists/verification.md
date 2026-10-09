# 验证结果

- JS 语法与 `git diff --check` 通过。
- `node --test tests/team_view/engineering-wait.test.cjs`：33 项通过。
- `NODE_PATH=/private/tmp/ase-rescue-ui-test-deps/node_modules node --test tests/team_view/browser/engineering-wait.test.cjs tests/team_view/browser/legacy-rescue.test.cjs`：14 项通过。仅运行增量测试。
- 使用原有 legacy-rescue 离线 fixture 检查截图对应两块：四栏均有序号，调查结果、方案说明、准备步骤分别分成三点；无关标题轮询保留原列表 DOM；1440/390 px 无溢出，查看了两种宽度截图；无交付写请求。
- 截图及临时验证脚本位于 `/private/tmp/ase-guidance-lists.W5XRfD/`。
- 按已读取的 before-dev / finish-work 规范核对前端只读边界、文档与变更范围。仓库无 `.trellis/scripts/get_context.py`，按现有 spec index 手动定位适用规范。

## 交付与存量

仅文本列表排版，未修改审批、重试、恢复、后台命令或数据。当前目录其他任务的修改不进入本次提交。
无需改库；执行 `./scripts/ase-console-service.sh restart` 成功后刷新浏览器加载冻结于新进程的前端资产。回滚本任务提交后同样受控重启并刷新。
