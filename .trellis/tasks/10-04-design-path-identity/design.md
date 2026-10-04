# 设计

1. `DesignerService._validate_affected_paths(design)` 为纯函数，仅校验 full repository-relative path 的语法。删除依赖 RepositoryProfile basename 的位置推断：同名文件不是同一文件，语言/构建标记也不能表达新增或修改意图。
2. 路径写入仍必须通过 Task allowlist/deny 与 PolicyBoundToolRegistry；不接受目录遍历、非规范路径，不授予 `.trellis` 等隐藏政策目录写入权限。错误实现位置由批准设计、明确来源引用及独立 QA/Review 验证，不能靠不可靠 basename 猜测。
3. `ProductionProjectDeliveryBackend._guard` 单独映射 `DesignerOutputRejected` 的应用静态原因到中文；不输出未知错误正文。保留 `INVARIANT_VIOLATION` 分类和原始 exception cause。
4. Reader/浏览器只对历史英文 class-only 句子做中文展示，不猜测旧记录已经丢失的具体原因，不改 seal 或 hash。

无 wire/schema、SQL 或权限变化。当前原生阶段未创建 Task，继续重试原阶段即可，不重建需求。
