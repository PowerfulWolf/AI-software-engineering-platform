# Goal

服务重启须先停止接收新写入/新操作，等待本实例已经开始的操作、索引与 owned 子进程
收尾并保存真实记录，确认后才退出并启动替代实例。任何未确认停止或保存失败必须拒绝
重启，保留服务/工作区/历史。暂不交付或操作生产 K1。

# Scope and decisions

- 采用有界 drain 当前完整 Operation，不强制取消模型调用，不新增假 timeout/provider
  transient，不退款或修改冻结预算、权限、verdict。已有排队操作保持 QUEUED。
- 同一短锁线性化 admission 与 submit/claim；HTTP 所有写入口 gate 并等待已进入的写请求。
- 当前操作中已授权的后续角色可以正常收尾，仍需真实 claim；关闭后不领取新的 Operation。
  drain 超时说明仍在收尾且不退出；必须有明确可重试/解除排空路径。
- 只有操作最终记录已保存、dispatcher/indexer退出、HTTP writes归零、owned native/tool
  process groups停止得到核验，才发布本实例、本次请求的 READY。无法证明则 REFUSED。
- 服务信号进入受控协调，不直接触发Uvicorn默认退出/二次信号force_exit。CLI restart与
  Settings apply共用实例nonce绑定的文件握手及替换锁，不能仅依据PID消失或旧成功标记。
- 初次加载旧版缺少握手的服务不得伪造READY；旧Run缺失事实不由本次停服回填。

# Ownership / allowed paths

控制平面 core/shutdown，host/transport/service lifecycle，knowledge index worker；
owned process tracker、native/structured runner与command executor；固定服务脚本/握手helper；
相关增量tests、schemas、docs和Trellis规范。所有Agent维护改动只在本仓库。
不操作生产平台/数据库、进程或业务工作区，不读取/输出生产凭据。

# Acceptance

1. 准确复现close返回而活动操作/独立子进程仍在执行的旧缺陷，再使新链路拒绝此情况。
2. 新submit/claim/HTTP写与关闭无竞态；进行中操作先正常保存，queued保留。
3. 真实SIGTERM→drain→真实stop/outcome保存→本实例READY→Console退出→新实例启动fixture。
4. 超时、保存失败、stop不确定、错instance/nonce、symlink、外来PID、并发替换均拒绝。
5. 当前读取可用，关闭失败有中文原因；重复信号不能强制绕过安全收尾。
6. 仅增量验证；保留独立QA/Review与既有native/synchronous模型语义；补文档及存量处置。

# Rollback

空闲且确认本实例停服后回滚代码；保留新增停止握手审计和全部Task/Run事实。
不通过删除草稿/改库/重置需求回滚。新版本记录需要兼容reader。
