# 设计

通用 `redact_text` 继续用于日志、URI、Context、Evidence 和知识文本。新增源码专用读取入口，
只在一个完整 assignment span 满足受限表达式 grammar 时保护该 span，再调用原 redactor。
仅经校验的 `.py` source_path 使用 AST/tokenize；strings/comments/f-/t-string 全span排除。
AST 必须为 single-name 对象的同名字段引用，或 single-name 与带路径符号的固定字符串之间的
路径除法；路径字符串另经原 redactor 校验。强 key/PEM/Bearer 特征先独立检查整个原正文。
它不会把任意 identifier 或 dotted RHS 当安全值，因此
`token=my.jwt.secret` 仍拒绝。所有 v2 mutation body/patch、CapturedMutations、baseline replay
和 required execution context 统一调用该入口，避免准备通过后在 Coder 启动时再次失败。
Patch 分开 hunk 两侧，精确行计数、文件路径及 metadata 使用通用扫描；未知/资源异常保守。
source_path 内存字段不进入wire/hash，父级 CapturedMutation 对实际 RelativePath 重验 before/after。

前端读取最近一次精确 rescue proposal operation。只有同一 Project、Requirement、Task、work item、
source/checkpoint、purpose 和 expected revision 匹配时才展示失败；FAILED/INTERRUPTED 不生成 plan
或审批，固定中文说明“保留草稿捕获失败”，下一步交平台执行服务/维护者并提供重新准备。后续
HANDLE_DELIVERY_WAIT 不能覆盖该精确记录。

存量只读定位已确认：失败发生在 capture，工作区与 index 未写入；不需要迁移或修库。
