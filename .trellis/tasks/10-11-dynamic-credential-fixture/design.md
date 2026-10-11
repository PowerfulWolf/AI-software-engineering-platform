# 静态语法证明

接口不变：`source_secret_occurrences(content, source_path=...)` 只返回检测事实，
不执行代码、不重写原文、不产生工程批准。`redact_text` 不变。

只接受 AST 精确 JoinedStr 的最终且唯一 FormattedValue：无 conversion/format_spec，
内容严格为 `{name}`。其值必须在同一普通函数/模块作用域有唯一直接前置赋值，右侧
为已有严格 stdlib import 校验认可的有界 secrets.token_* 调用。

普通字段引用、None、dataclasses.field 和未知函数不能证明动态凭证。
拒绝参数/global/nonlocal、循环/条件绑定、所有重绑/删除、闭包与 comprehension/lambda
作用域、生成器别名和动态执行。仅替换与该插值精确对齐的 secret_assignment 匹配。
强凭证规则始终检查未改动的完整原文。

Good：局部 credential=secrets.token_urlsafe(32)，后续 f"token={credential}"。
Base：普通固定 `"token={credential}"` 仍被检测。
Bad：同名参数/第二赋值/未知生成器/格式转换/静态前后缀/凭证来源不在完整 hunk 内。

先 red source/capture 测试，再最小修复，然后完整原现场只读重放；无存量数据修改。
