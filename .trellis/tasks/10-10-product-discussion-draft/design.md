# 设计契约

Product 讨论与其他交付操作分开处理顶层当前控制资格：故障期间仍渲染 Product 草稿，其他
操作保留原 gate。草稿 identity/key 包含 Team、Project、Requirement、checkpoint、stage、
当前 Operation、source drift 与预算，瞬时读取 issue 不进入 key。缓存复用不改变这些事实。

每个 form 冻结精确绑定而非读取可变 request 引用。在事件入口、每次截图 POST 前和
Operation POST 前检查：form 仍连接、当前控制资格、当前 Project/Team、当前精确讨论 key、
缓存仍指向该 form，无 active Operation 或进行中提交。故障说明独立只读；编辑许可与
执行许可分离。按钮复用现有 data-delivery-control 与 setDeliveryControlDisabled。

不使用现有快照授权旧 callback，不依赖按钮 disabled 作为唯一门禁。异步边界后失败时
保留文本/截图，说明未继续提交；已上传的单张附件不等于受理需求。当前成功受理才清草稿。

根代理将独立复核并同步组织规范，本子任务不修改共享 incremental-polling 规范。
