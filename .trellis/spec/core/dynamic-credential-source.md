# 动态凭证安全测试源码

## Scope and signatures

`redaction.source_secret_occurrences(content: str, *, source_path: str | None)`
与 `patch_secret_occurrences(content: str)` 用于完整草稿封存，返回 occurrence facts。
`redact_text` 仍用于日志、URI、任意文本且无源码例外。

## Contract

- 只对可完整解析的 `.py` 源码应用有界 AST 语法规则，不执行文件、导入或表达式。
- 仅精确 `{name}`，无转换/格式，且是 JoinedStr 唯一、最后的插值；只掩蔽精确
  secret_assignment 匹配的临时检测值，原文件/patch/body/hash/wire 保持原样。
- 名字只能在同一模块或普通函数体内唯一、直接、前置单 Name Assign 绑定。右侧必须
  是可信模块级、无别名/重绑/逃逸的 secrets.token_hex/token_urlsafe/token_bytes 有界
  整数调用。引用、dataclasses.field、None、参数和 helper 返回值不证明动态生成。
- 参数、global/nonlocal、条件/循环绑定、删除、任何重绑、捕获外层名字、类/lambda/
  comprehension，以及可识别 namespace/frame/mock-patch 反射入口撤销例外。
  明确修改无关对象的 monkeypatch.setattr 不授予新权限，也不自动否定其它方法的合法局部值。
- 强 key/Bearer/PEM 对原文独立扫描。普通字符串、注释、静态后缀和同串其它固定凭证
  不能获得整串豁免。源码规则不是任意未知调用副作用的运行时证明。
- patch 每个 hunk 的两侧分别验证；不从缺失文件上下文推断 import 或绑定，不跨 hunk
  借用证明。无法解析保持保守拒绝。既有 request-local 有界 cache 生命周期不变。

## Validation matrix and examples

| 输入 | 结果 |
|---|---|
| 直接 credential=secrets.token_urlsafe(32)，后续 f"token={credential}" | Python source 可完整封存；generic 仍检测 |
| 同一源码用于非 Python/日志 | 拒绝 |
| 固定值/第二 writer/参数/闭包/格式转换/静态后缀 | 拒绝 |
| 显式 mock.patch 动态拼接 secrets target | 拒绝 |
| 同串另一 password 或强 key | 拒绝 |
| 缺 import/binding 的 partial hunk | 拒绝 |

Good：动态生成负向安全测试输入，经 real Git capture/wire/verify 字节不变。
Base：普通字符串 `"token={credential}"` 继续检测。
Bad：删除负向断言、允许任意 f-string、跳过 secret gate 或改写历史 stop/outcome。

## URL-decoded runtime field references (2026-10-16)

`source_secret_occurrences(content, source_path=...)` also recognizes the exact Python
expression `password=unquote(parsed.password)` (and the same exact assigned credential
field). The complete source must prove a preceding module-level
`from urllib.parse import unquote`, without aliasing, rebinding, escape or observed
namespace/reflection mutation. The decoder takes exactly one positional argument: an
attribute of one runtime object name whose field equals the assigned field. No literal,
unknown callee, chained decoder, extra/keyword argument or function-default exception.
Inspection never executes or imports the supplied source.

This is syntax classification for full original source bodies, including the Git base
body of an unrelated edit. It does not authorize storing actual credentials. Generic
log/URI scanning stays unchanged; original source still receives the independent strong
key scan. Strings, comments and incomplete patch hunks cannot borrow a missing import.
`CapturedMutations` must retain and revalidate complete before/after bytes and patch;
Git history is not an exemption from sensitive-body validation.

| Input | Result |
| --- | --- |
| Exact proven decoder of same-field reference in Assign/AnnAssign/call keyword | Preserve source bytes; full Git capture/wire verification allowed |
| Direct existing `password=settings.password` | Existing source behavior unchanged |
| Literal/unknown argument, different field, alias/rebinding/escape/reflection, missing import | Sensitive; no receipt/admission |
| Same syntax in log/config, string/comment or unproven partial patch | Existing conservative detection |
| Fixed credential or strong key elsewhere in the complete source | Sensitive; decoder grants no whole-file exemption |

Tests: `tests/context/test_url_decoded_source.py` and the real Git BEFORE-body regression
in `tests/git/test_mutation_capture.py`. The latter commits the decoder reference first,
changes only an unrelated value and asserts complete exact wire/patch/index preservation.
Keep existing source/dynamic-credential/patch and continuation refusal regressions.

存量数据处置：Run5 的 local_execution_limit、真实 owned stop、UNKNOWN 历史及完整草稿不改。
修复加载后只使用公开 HANDLE 在 Task lock/idle fence 中重新完整封存，再使用当前事实提供的
精确恢复路径；维护 probe 的通过不是 receipt、progress、candidate 或 QA/Review 结论。

## Tests, stored data and rollback

增量：`tests/context/test_dynamic_credential_source.py`、`test_source_secret_detection.py`、
`test_generic_redaction_scope.py`、`tests/git/test_mutation_capture.py`。必须覆盖 UTF-8
位置、多方法局部同名、各种 writer、反射、真实 Git 无写入和 wire 重验。

存量无需改库或改源码。读取当前停止事实后，由公开平台协调器重新完整封存并明确批准
原 Task 的下一执行；不把 UNKNOWN 报告改成成功，不退款。若有使用新语法例外封存的
完整 records，回滚 reader 必须保留兼容检测；不能删除记录或改其 hash 迁就旧 reader。
