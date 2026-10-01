# 精确当前快照

`RecoveryInterruptionPlan.stopped_capture: CapturedChanges | None`缺省None且序列化排除None，
保留旧digest。None继续要求完整原seed未变；有值绑定同Task/attempt1/原worktree/branch/
source_revision/base_revision，完整patch、路径库存、文件SHA和index SHA进入新plan digest。

首次提案在Stopped Task锁内调用既有有界、只读、双采样capture_changes，沿用有效权限与
denied_paths。仅与seed不同才增加stopped_capture。已存在计划在审批前和新Worker真实claim
准入时verify_capture，任何漂移拒绝，不重新生成或覆盖旧计划。capture的工作区身份必须与
原seed完全一致。旧seed的完整性与lineage仍重验，但不把它当作已经运行后的最新字节。

既有Task/events/queue/admission/old lease/routes/artifacts/target/current-policy检查全部
保留；新invocation仍是一次、fresh Run+next generation，plan digest间接绑定当前capture。
Console审批说明给出保留文件清单和摘要，旧审批不得隐式适用新的工作区。

`prepare_workspace(target: WorktreeRef)`在_execute已打开目标后取得停止Task锁，比较原seed
工作区身份、plan/dispatch/invocation lineage并重验精确stopped_capture。此分支不能再次
调用`RecoverySeedService.seed()`，后者用于尚未执行的原始seed，会错误拒绝合法新改动。
普通恢复继续原seed逻辑；最终真实Worker下authorize仍再重验，不从prepare直接获得运行权限。

验证矩阵：unchanged→旧计划；合法pre-proposal changes→新capture计划；post-proposal
内容/index/HEAD drift或capture身份漂移→拒绝；危险路径/越权内容→拒绝；completed route/
artifact/replacement receipt→原拒绝；新claim下实际Coder读取全部保留字节并经QA/Review。

存量：保留e35017a新Task及20文件dirty工作区，旧失败Operation不改。加载修复后继续提案，
逐文件/摘要核对、按用户已授权完成精确审批，再观察真实lease/run/前端中断状态收敛。
