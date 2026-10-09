# 设计与契约

## 存储

FileConsoleOperationStore 使用独立 16 MiB Operation record admission budget。
实际 JSON UTF-8 编码长度包括转义与缩进，不能仅以 patch 字节或字符长度代替。
这不是 Schema 所有合法值的推导最大值，仍允许 Schema-valid 超预算记录被存储边界拒绝。
model-call 保留独立 16,000 bytes 预算；Team 知识文档上限不改变。
读路径保留 _read_regular 的 regular/no-symlink/有界读取，及所有 model/integrity/sequence/
hash chain 验证。写入发布前验证大小，exclusive link + fsync append 保持。
schemas/console-operation.schema.json 与原 operation wire bytes/hash 均不变。

## HTTP 与展示

GET /api/v1/operations 和 GET /api/v1/operations/{operation_id} 的已知 store/model/I/O
读取失败返回 503 OPERATION_STATE_INVALID 与固定中文安全摘要，无 partial success、
原错误正文、路径、输入或 traceback。invalid/missing operation identity 保持 404。
GET /api/v1/console 的 delivery_ready 不被错误改为 false；浏览器的 operationsAvailable
独立禁止写操作。需求内使用同一就绪原因显示下一步，不能仅依赖可关闭的全局通知。

## 验证矩阵

| 输入 | 预期 |
| --- | --- |
| >256 KB 且 <16 MiB 合法完整计划 | 完整读回和 HTTP 200，digest/chain 不变 |
| 实际 UTF-8 JSON >16 MiB | 写入拒绝，无终态/临时文件；读取拒绝 |
| digest/chain/sequence/path 损坏 | 不返回部分记录，安全 503，无信息泄露 |
| operations 不可读、Console ready | 就绪事实保留，需求内说明，交付控件不可用 |
| operations 恢复 | 最新精确结果重新可见，独立确认后才能批准 |
| Console/runtime/Team/Project 门禁不满足 | 对应中文原因，不提交、不伪造方案 |

本次先修合法存量的兼容读写和明确反馈。未来 Operation 分页及重正文 artifact 引用
需要另行版本化设计，不能通过删除、截断或原地瘦身当前记录解决。
