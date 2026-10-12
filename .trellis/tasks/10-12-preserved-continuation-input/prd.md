# 已保留工作区的续跑阅读输入

## 实测问题
原 K1 第 3 轮 Context 248568 tokens，最终 native 输入 285444 > 256000；包含仍必需的完整历史 coder_reapply 旧补丁，以及额外的 135493 字符当前工作区草稿。两份补丁不是相同内容；不能按重复正文去重或直接提高容量。

## 目标与边界
对已完整核验的 v2 同工作区续跑，阅读输入给出确定、带版本的保留现场 manifest，Coder 通过既有受控 read_file / git diff 读取现存源码。完整 capture/patch/变更体永久保留、每次完整核验，旧 coder_reapply patch 继续全文 required。没有新执行权、审批、预算或结果改写，v1 保持全文。

## 验收
- 真实 Git 生成大草稿→受控停止→原 Task 新 claim：preview 不发布，prepare 相同且只发布原 one-use admission。
- manifest 绑定 scope/source/receipt/capture/patch SHA 和 bytes、每个变更前后 SHA/mode/size、删除；无源码正文。
- 现场/receipt/stop/权限漂移仍拒绝，完整读验证未减少。
- 同最终容量 gate 检查完整旧补丁、当前元数据、包装与输出 Schema；仍超限拒绝且不调用模型。
- 生产第 3 轮精确输入只读重放，记录估算变化；不保存生产 prompt 或源码到仓库。
- 沿公开 same-Task capacity PAUSE/RESUME 继续存量需求，无 SQL/历史重写。
