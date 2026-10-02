# 增量刷新设计

## 原因与取舍

原 refreshSnapshot 虽然会跳过完全相同的快照，但任一需求、模型操作或索引变化都会调用
render，清空整个 content/detail。仅恢复带 data-key 的 details.open 无法保留节点、正文、
焦点或帮助弹层；调用诊断和规范正文原本还缺少稳定的 key。

按优先级检验：过宽刷新依赖导致设置重建；无身份的详情块导致折叠；节点重建导致异步正文
缓存丢失。真实浏览器两个原始回归均在修复前失败，直接断言相同输入及诊断节点存活。

## 接口与数据流

GET facts → existing serial refreshSnapshot → render({incremental:true}) → scoped renderView
→ viewGroup/reconcileViewChildren → source-signature matched viewBlock。
签名仅存 WeakMap；不得把配置或凭证放入 DOM 属性。纯容器才可标为 group，有命令闭包的
节点必须按关联 facts 整体替换，不能只比较 HTML 外观。render 默认保留显式导航/编辑语义。

## 边界

content 按页面依赖，detail 按选中实体、相关任务、审批与 readiness 依赖。项目/实体 key
变化切换整个对应 surface。相同文档 URI+内容或操作身份+事实保留原节点。任务心跳更新
诊断中的独立 activity，不重读完成的模型调用正文。知识列表/规范/学习事实均参与触发判断。
Settings metadata 可更新，form 由草稿基线、Section 和版本契约限定，保留写入中的表单。
对精确 checkpoint 的变化重新生成控制；可见通知和系统阻断继续运行原有检查。

## 验证与回滚

覆盖无关变化、当前实体变化、timestamp-only、正文缓存、滚动/选区、任务弹窗、资产列表
独立更新和 stale approval。沿用 Project navigation/async fencing；只运行相关增量测试。
前端代码回滚并刷新即可，无持久化数据迁移。
