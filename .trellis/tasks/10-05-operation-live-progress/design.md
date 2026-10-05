# 根因与方案

生产复现由主代理只读获取：Requirement 已 PLANNING，“继续交付”的同一 Operation 仍
RUNNING，原记录只有动作/status/time。显示内容本身未派生当前交付阶段。新增回归同时发现
operation history 父 ol 未 keyed，行签名不会进入逐行 reconcile，历史行会被整个列表替换。

新增 currentOperationProgress，精确绑定 Project/Requirement/当前RUNNING交付Operation，
复用 deliveryPhase/requestNodeExecution。当前阶段/原因/责任/下一步同源供 history 与 ACTIVE
notification；主标题当前阶段，原动作/status/time另列。父列表viewGroup，行签名包含record
与派生progress，确保同Operation bytes不变但Task/Req变更时刷新当前行，历史行保持DOM。

activeOperation增加可选Project过滤，current node和preparingTaskExecution精确传参，防止
foreign Project相同delivery ID遮住本Project执行事实。其余调用及授权契约保留。

# 产品与审计

有限动作目的描述意图；Continue写“接续已保存的交付进度”，不假定Product已批准。
RUNNING不冒充native角色claim；产品等待/工程等待/排队优先。
opaque ID和输入checkpoint折叠并明确为“发起操作时的需求版本摘要”。不生成阶段历史或
百分比，不推断模型在线或已完成验收。通知保持原ACTIVE key，关闭后阶段变化不再弹出。

生产续验发现SUCCEEDED + result.stage=BLOCKED的历史命令显示“执行成功”而忽略封存阶段。
追加recordedOperationOutcome以原result.stage为唯一依据，显示当次阻塞/等待/交付结果，
命令成功标签改为“命令已完成”，原SUCCEEDED放折叠审计。后续Req DONE不覆盖原BLOCKED。
仅result.stage DONE表示当次交付；中间阶段/关闭/缺结果不推断完成。固定Designer missing
planning handoff中文精确映射，原诊断保留，交接故障由工程处理，不新增技术审批。
完成命令badge局部改为静态中性灰，阻塞标题局部CSS红色；不改全局badge，也不以命令完成
把阻塞结果染绿。固定诊断只表达交接尚未通过校验，不推断实体文件缺失。

# 影响与存量

只读前端，无Schema/API/持久数据变化。正在运行的Planner保留；不生产写、不部署。
部署资产刷新即可让旧需求受益，原Operation bytes、审批和预算保持。
