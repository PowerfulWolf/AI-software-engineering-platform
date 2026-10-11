# Contract design

新增RejectedCoderOutputCheckpoint及RETRY_REJECTED_CODER_OUTPUT，独立于真实interruption。
封存原request/start/outcome、被拒progress、稳定拒绝code、completed stop、原claim、
Task intent/revision和完整mutation capture/inventory。新增optional字段省略None，旧摘要不漂移。
只处理机器可核验的progress语义拒绝；publication receipt不等于Task交付checkpoint采纳，
若已有StateEvent消费或候选/独立verdict则禁止本路径。

任务锁→queue authority→Task row fence内验证exact proof并一次消费，保持原Task/source/branch，
attempt+1且无transient退款。新claim admission重验完整现场，并向Coder提供原拒绝理由；
不得把原非法报告修改后当作accepted progress。现有QA/Review和候选门保持。

| Case | Required result |
| --- | --- |
| stopped+精确语义拒绝+完整合法现场+预算 | 封存，只允许新执行，不重放旧产物 |
| active/unknown stop、source/HEAD/index/inventory/claim漂移 | 保留现场，拒绝消费 |
| 原progress已被StateEvent消费或存在candidate/verdict | 本路径拒绝 |
| exact consume replay | 不增加第二次attempt/副作用 |
| changed decision/proof | 原子拒绝 |
| 新输出合法 | 经普通progress/candidate/QA/Review门继续 |

具体字段和schema由实现worker锁定后同步core spec，完成前逐项审查。
