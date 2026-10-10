# 通知颜色与图标语义

## 问题与目标

真实恢复CONTINUE Operation执行中，通知标题正确但图标显示绿色✓。operationNoticeFor正确
产出kind=info，buildNotification把非error/warning的所有kind映射success。正在执行/排队和
普通提示因此冒充成功。仅修复图标映射和info CSS，不改变任何执行事实或通知资格。

## 范围

- app.js仅buildNotification两行图标与class选择。
- style.css新增settings-result-icon.info蓝色样式。
- browser通知测试仅追加语义图标case；root同步规范。
- 不改变key、ack、signature、focus、草稿、controls或运行节点claim门禁。
- 当前K1执行中，仅改磁盘代码，等待安全空闲边界加载，不操作生产/模型，不提交。

## 验收与验证

QUEUED/RUNNING真实通知显示i/蓝色info，无success class与✓；已有success绿✓、warning i和
error !保持。普通administration info同样蓝色。关闭ACTIVE后轮询不会重新弹出。
先新增真实Chrome测试捕获当前错误，再最小修复，仅运行新增图标用例。
命令：NODE_PATH=/tmp/ase-ui-browser-check-20261010/node_modules node --test
--test-name-pattern='notification semantic colors' tests/team_view/browser/notifications.test.cjs。
并运行app.js/test语法检查、git diff --check。

## 存量与回滚

无需改库或修改Operation/审批/历史。新assets在安全空闲边界加载后浏览器刷新生效；运行时
不得热换已冻结资产。回滚两行映射和info样式，不改变任何后台状态，旧误绿图标可能恢复。
