# 项目历史操作与当前通知

## 实际复现

2026-10-10真实只读Chrome打开ai-project需求页，正常RUNNING的K1被2026-10-04创建失败弹窗
遮住。精确记录operation_bd2ec8d7ce12164a0d49bf0f2b3eaba2，CREATE_REQUIREMENT，提交
10:50:50Z、结束10:51:00Z，Project project_ai-project_034252eb3595，没有delivery target。
当前筛选只按相同target/action覆盖旧操作，独立创建失败不会被当前K1的继续操作覆盖；新会话
没有ack，因此把陈旧无目标失败视为当前需操作。全局operations面板隐藏，需求历史只接受
精确target，旧创建失败还缺少非弹窗的可读入口。

## 明确语义

- 仅改变浏览器通知资格和只读历史。Project严格匹配当前已确认Project，不根据标题猜需求。
- 首次成功读取Operations时已存在、且没有本Project可访问Requirement目标的terminal/attention
  记录归历史，不能自动遮挡当前需求；包括创建失败和已删除/退休的目标。
- 本会话已观察到QUEUED/RUNNING、已受理submit，或首读后新增operation，其新失败仍可提示。
  使用操作身份与本会话观察，不用固定时间阈值，不清持久ack或修改历史。
- 已存在且仍可访问的精确target审批/等待/失败保持现有资格，跨Project不能压掉当前decision。
- 当前Project列表末尾及无需求空态提供默认折叠“项目操作记录”；说明未关联可访问需求，
  展示全部相关记录、真实状态/时间/原因和工程ID，键盘可达、textContent安全、不额外GET。
- 不改变后台state、审批、历史hash、执行claim或服务运行；当前K1运行中不重启/热换资产。

## 验收与增量测试

实际形状旧CREATE失败+当前K1 ACTIVE，首会话只显示当前ACTIVE；旧无目标/已删除目标记录仍
能在项目历史逐条读取。历史详情展开后轮询保留，不取外Project、不执行写API、不解析HTML。
本会话ACTIVE→terminal、新submit即时失败、之后新增terminal仍提示；当前精确target需处理
不被旧无目标记录或外Project操作遮盖。关闭后不复活，原operations bytes保持。
先Node/isolated Chrome red→green，只跑相关增量、JS语法与diff check。

## 存量与回滚

无需改库、清历史或重建需求。已读旧操作按当前Project进入只读历史；已有精确审批继续可用。
新兼容资产仅在安全空闲边界加载后刷新生效。回滚前端会恢复旧弹窗问题，所有进度/审批/
Operation保留，未新增backend权力。
