# 上游固定阶段操作提示统一中文只读展示

## 问题与目标

已有 Requirement 在待产品审批时，将固定英文 `Review product_spec and approve this exact
checkpoint, or reply with revisions.` 作为 next_action、blocker、execution.next_action
展示。用户已要求阻塞原因与操作提示使用中文，旧英文记录不能因此被修改。

从 `multi_directory/service.py` 确认 14 条固定英文控制提示，包含准备、讨论、回复、产品审批、
批准进入设计、设计重检、计划、执行、已批准知识恢复、规范冲突及关闭重开。补入现有只读精确
翻译，并在执行摘要、建议操作与历史 Operation 下一步使用同一展示函数。

## 验收标准

- Python reader 与兼容旧 server 的 JavaScript 对同一有限集合返回一致中文。
- 真实待产品审批页面显示中文动作，原 snapshot 与 Operation 内容保持英文，审批按钮不变。
- 用户正文引用这些句子、未知文本及动态错误不因新增映射被宽泛替换。
- 只跑三份相关测试文件及对应 Ruff、mypy、JavaScript 语法和 diff 检查。

## 存量数据处置与回滚

无需改库或迁移：历史 bytes/hash、journal、Task、Operation、checkpoint、审批及计数全部保留。
前端刷新即可兼容旧投影；Python reader 需在当前 Operation 自然结束、服务空闲后部署重启。
无需新建需求或重新批准。回滚恢复本次展示提交，空闲时重启并刷新页面。
