# 执行时间与协调边界对齐

## 目标与范围

截图中的 Manager 协调轮次与上方时限表格共用左右内容边界：标签与角色列对齐，输入框从
第一数值列延伸到最后输入框的右边缘；表格与字段之间保留 16px 间距，字段垂直居中。
600px 以下标签与控件上下排列。仅修改 app.js、style.css 和布局规范，不改变配置契约。

## 验收与验证

检查 1440/768/390px 下实际 CSS 几何、左右对齐、间距、无横向溢出及配置提交。
增量命令：NODE_PATH=/private/tmp/ase-ui-test-deps/node_modules node --test
tests/team_view/browser/settings-layout.test.cjs tests/team_view/browser/design-budget.test.cjs。
另执行 node --check 与 git diff --check。不得执行全量测试。

## 回滚与存量数据

回滚本次布局改动即可，不涉及数据迁移、旧 Task、审批或 Operation。
当前目录其他恢复功能改动不属于本任务。

## 完成记录

新增 execution-time-fields 容器与 execution-coordination-row，共用时限表格列定义及内边距。
真实 Chrome 几何核验：1440/768px 左右边缘差为 0px、垂直中心差为 0px；三种宽度均为
16px 间距且无横向溢出，390px 标签与控件顺序堆叠。验证截图已人工查看。

执行指定文件中的两个受影响用例（--test-name-pattern='Settings pages share|Manager and
execution-time'）：2 passed；node --check、git diff --check 通过。未跑全量测试。
