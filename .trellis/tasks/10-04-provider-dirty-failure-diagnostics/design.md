# Design

Responses adapter 继续使用同一 `_safe_failure` 入口。工作区 dirty 时将原本已经限长/脱敏的提供方消息包在固定的 `failed provider route left repository changes` 前缀后，保留失败原因但不改变不可重试策略。异常文本先经过 `safe_diagnostic`，不会写入 prompt、响应正文或密钥。

交付 checkpoint 是 append-only 事实，不能在状态读取时修改。状态读取返回的 drift diagnostic 由控制层明确映射为人工恢复动作；普通 `RUN_DELIVERY` 只在当前 preparation 与 checkpoint 一致时显示。
