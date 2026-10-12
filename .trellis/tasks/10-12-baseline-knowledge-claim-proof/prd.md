# 历史知识准备失败的精确 claim 停止证明

生产 K1 的 attempt 1 在只读知识准备阶段形成完整失败记录，未到主 Coder 调用；之后 attempt 2 已有真实本机停止，attempt 3 是调用前容量等待。现有基线调查将所有无主调用的 claim 只按容量或 preflight 分类，错误拒绝 attempt 1，导致原需求无法申请新源基线。

目标是在保留所有原执行历史的前提下，独立验证历史知识失败：精确 scope lane、真实原 claim、历史 step、完整 Context/Task、冻结知识快照、全部 intent/outcome、独立 structured route 记录。必须至少存在真实 FAILED outcome；单独缺少 main start 不能构成证明。所有主调用、native、route 和 artifact 否定检查继续生效。返回摘要 proof 仅用于 quiescence facts，不是 verdict、审批、停机收据或退款。

验收：合法知识准备失败可参与原 Task 基线计划；缺 outcome/独立记录、孤立或错误键记录、claim/source/snapshot/context 漂移、未结束路由、native/main/route/artifact 矛盾均拒绝。保持当前精确审批、原工作预留、dirty 工作区、capacity 未调用证明和 QA/Review 不变。

存量数据：不改库、不回填历史。发布后以同一个原需求重新准备精确基线计划；若记录不能完整验证则保留阻塞。parent 负责生产操作。
