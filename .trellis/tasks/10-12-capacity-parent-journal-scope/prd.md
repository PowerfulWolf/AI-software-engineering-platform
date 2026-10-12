# Legacy capacity 观察内复用完整 parent journal 解码

## 目标和范围

LegacyContextCapacitySourceReader 的一次同步 source 观察会独立检查原需求退休状态，并在前后
两次定位 parent。原实现每处构造新的 JointJournal，重复解码相同完整历史。仅在这一观察内
传递同一个局部 journal map，复用现有 exact-byte、exact-predecessor 解码机制。

允许修改 context_capacity.py、专用增量测试、本任务和专用 spec。不改普通 native reader、
JointJournal 的公开契约、Context 全目录扫描、HTTP/前端、Schema、SQL、审批和执行状态。
其他作者同时工作，不能回滚或提交其改动；禁止触碰生产实例、模型和共享数据库。

## 验收

1. 真实临时 Team/Project、退休和 replacement journal fixture 的三轮观察仍完整读取每个
   历史文件并重新计算字节 SHA；Journal 每文件读 3 次，独立 regular preflight 再读 3 次，
   相同历史仅解码一次，当前 parent/retirement 检查照常执行。
2. 同大小/mtime 历史篡改、历史缺失、错误 predecessor 和 symlink 仍拒绝；新 tail 必须可见。
3. 不缓存 current Task、SQL、claim、Git、权限或 READY；既有前后 source 检查次数不变。
4. 同一 reader 的下一次公开观察重新解码完整历史；正常和异常退出都清空局部缓存，包括
   异常 traceback 被调用方保留的情况。
5. 先做真实 file-store 计数红测，再增量 pytest、Ruff、strict mypy、独立 review 和 diff check。

## 存量数据处置与回滚

不修改任何 durable bytes、审批、Task、Requirement、Operation 或保留现场，不需数据迁移。
当前交付执行期间不部署；空闲后由 root 按受控服务流程加载修复，同一个原需求继续公共流程。
回滚仅恢复原重复解码组合，保留全部已有历史；不得重建需求或修改数据库。
