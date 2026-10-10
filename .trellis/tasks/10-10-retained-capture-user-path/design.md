# 契约和验证边界

1. `source_secret_occurrences(content, source_path=...)` 保持纯函数和只返回 occurrence facts。
   在完整可解析 Python 中识别 AST 上的非值类型注解并检查真实右侧，不能只删除冒号匹配。
   安全表达式必须证明是标准库/元数据，禁止宽松豁免任意调用、字面量或整个 tests 目录。
   原始字符串、注释、日志、配置和强凭证检测不变；所有 capture/wire/context 使用同一规则。
2. 已停止事实验证 exact invocation、claim、Task/policy、scope、stop/start 和当前进程条件。
   停止记录只能证明停止，不证明结果或封存完整。缺捕获始终无可用 resolution。
3. `DeliveryWaitHandling` 可加省略 None 的有限诊断类型。旧记录 hash 和 identity 保持；
   新失败类型参与新 identity，禁止异常原文、源码和潜在密钥进入存储/页面。
4. 页面保留明确“平台修复后重新处理”动作，调用 HANDLE，而非仅只读 INSPECT。
   按钮仍绑定当前 exact wait；审批和执行状态不可混淆。

Good：真实 TIMEOUT + 已停止 + 合法完整草稿 → receipt → frozen policy → 原需求继续。
Base：合法停止 + capture 拒绝 → 明确封存失败、现场保留、无继续授权、显式重新处理。
Bad：外来停止、活动执行、敏感值、缺记录、权限漂移 → 拒绝且不可绕过。

新增 fixture 分类尚需独立审查，不以候选特例或人工静默修改绕过边界。
