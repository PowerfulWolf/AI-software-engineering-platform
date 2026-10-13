# 设计
读侧用真实 Team/Project manifest + verified retirement/journal 生成不可变排除集合；Operation store 完整校验所有字节后过滤，cursor inventory 绑定排除集合。写侧复用正式 close/delete guard 的历史 Task 进程锁、队列取消与租约核验；仅在止停证明内调用受管 Git archive/remove seam。原像保全与清理分开封存，可幂等重放。主 checkout 只在用户明确授权合入时 fast-forward main，不生产 SQL 改库。

独立验证不是普通Task；只接受完整计划核验的已completion/abandonment reservation。普通settlement前只读停止预检；settlement后获取现有dispatch authority fence，保持到parent终态/tombstone落盘，避免新reservation竞争。
