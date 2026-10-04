# 实现记录

已推送的 `d53edad` 修复真实 Git 根的分支占用检查、首个 Coder 启动前工作区冲突分类、严格 preparation 校验及正常过期租约回收。目标 clone 已快进至该提交。

后续补齐：

- 终态 Coder 尚无 candidate 时，即使主基线更新造成 preparation diagnostic，继续入口仍进入完整的精确恢复校验，不 replay 原终态 Task。
- 普通 Coder recovery 与 pre-agent restart 一致，从已批准 Product 分支生成未占用的稳定 successor 名称；显式分支仍按精确名称拒绝占用。
- bootstrap queue item 与 step 校验所有不可变字段；只有启动失败允许正常 reaper 已回收的历史 claim。其他未执行证明仍拒绝 claim 历史。
- 唯一 plan 校验 source revision 和 admission receipt SHA-256；Worker lock 父路径拒绝 symlink，活动锁拒绝恢复。

存量 K1：`task_continue_db73e341d3cad54414de6c3bc30234eb` 已终态阻塞。此前真实运行中主、备 Responses 返回 504，CLI 被中断后留下三个未跟踪实现文件；再次续跑在 162ms 内被 dirty 启动边界拒绝。不能据此认定模型主动越权。原工作区与失败记录保留，必须重新捕获并批准新基线下的精确恢复计划。

不修改生产 MySQL，不清空 dirty 工作区，不改旧 verdict 或审批，不绕过 QA/Reviewer，不自动 merge。
