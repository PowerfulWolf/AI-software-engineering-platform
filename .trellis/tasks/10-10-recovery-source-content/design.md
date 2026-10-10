# 契约与验证

恢复 patch 是有显式 Git header 与真实 hunk 的源码，不是任意日志正文。
`patch_secret_occurrences` 对每个完整hunk side使用现有source detector，metadata、未知语言、
不完整或不能解析的源码仍保守拒绝。普通标题、路径、rationale继续用redact_text。

Good：新增Python模块 import secrets + token=secrets.token_hex(16) 原字节可捕获。
Base：旧无token补丁的wire与hash不变。
Bad：token字面量、未经证明的属性、metadata密钥或伪造hunk均不能封存。

先跑真实Git回归Red，再替换两处错误检测调用，复跑定向capture/model/secret tests。
