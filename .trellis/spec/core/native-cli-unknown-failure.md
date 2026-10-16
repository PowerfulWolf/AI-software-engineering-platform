# 原生退出未知不能证明临时故障

## Scope / signatures

`agents.codex_cli._classify_cli_failure(CodexInvocationResult) -> tuple[AgentErrorCode, bool]`
只消费 `_select_main_cli_failure_diagnostic` 选出的完整可信 stderr 主错误。
`_recognized_cli_failure` 保留 AUTH/INVALID/QUOTA/RATE，并明确识别有界主诊断中的
HTTP408/500/502/503/504 和连接失败，作为 PROVIDER_UNAVAILABLE。

## Contracts

- 非零原生退出不是临时提供方故障证明。无可识别诊断返回 PROVIDER_UNAVAILABLE、transient=false；
  原输出摘要、退出和停止记录保留，不把 unknown 改成 AUTH/INVALID。
- 完整且来源明确的限流/额度/服务故障才允许原 transient flag；未知、不完整或信号退出不得退款。
- stdout、MCP/background/tool日志不升级为原生错误；截断/主错误JSON完整性门保持。
- typed classifier不批准恢复，不改Task/预算/历史；后续由同一 NONTRANSIENT_INFRA taxonomy
  和冻结普通工作额度路由调查或终局。

## Validation matrix / required tests

| 输入 | 结果 |
| --- | --- |
| rc1，无stderr、普通输出、未知主错误、背景HTTP503或stdout认证词 | PROVIDER_UNAVAILABLE / false |
| 完整主错误HTTP429/usage limit | 原RATE/QUOTA / true |
| 完整主错误HTTP408/500/502/503/504、明确connection failed | PROVIDER_UNAVAILABLE / true |
| 完整主错误AUTH / INVALID_SCHEMA | 原专用code / false |
| 信号退出 / 不完整截断主错误 | 原nontransient路径保持 |

`tests/agents/test_cli_unknown_failure.py` 覆盖新矩阵及真实adapter边界；
`tests/agents/test_codex_cli.py` 保持权限、dirty/provider fallback和真实有界子进程回归。
公开Host真实unknown child测试在nontransient-delivery-routing任务记录。

Good：未知错误保持未知且可调查。Base：可信服务故障保留有界重试。Bad：仅因rc非零或fallback
code等于PROVIDER_UNAVAILABLE就声明transient。先前只修truncated出口漏掉完整unknown出口。

## 存量数据处置 / rollback

不追溯改写任何已保存error/transient、Run、stop、retry或审批。历史unknown等待的公开受控结案
由独立delivery-wait修复处理。无数据库迁移；回滚代码不会删除历史，旧版本会重新引入未知重试。

## Safe main-error detail in future native failures (2026-10-16)

### Scope and signatures

`CodexCliAgentAdapter.run` adds a safe display summary only to its ordinary nonzero provider
failure's existing `AgentFailure.message`: `; main_error=<JSON string>`. `_safe_cli_failure_detail`
selects the summary; the decoded string is at most 500 characters. `_failure_diagnostic` retains
the original cause/rc/two-hashes format, and `_classify_cli_failure` still consumes the original
invocation. New display text cannot supply retry, transient, refund, stop or approval authority.

### Contracts

Remove the complete exact configured proxy key from the already controlled environment before
redaction/selection. A configured but unavailable key requires hidden detail. Apply complete
stderr redaction before selecting a main error so multiline private-key material cannot become
a fake safe line; apply URL/control/credential cleanup before truncation. Select only complete
untruncated native main stderr. Never promote stdout, MCP/background logs or arbitrary transcript.
For main JSON, expose only a string `error.message` or top-level `message`, excluding siblings,
request, headers, prompt and stack. Missing/incomplete/non-message content returns explicit
unavailable text. Dirty policy, timeout and guard-abort paths keep their original metadata.
`safe_diagnostic(text, *, limit=500, exact_secret=None)` also removes a supplied exact key after
full ANSI/OSC/control/URL normalization and before the final bound. Cleanup can reconstruct a
split credential; raw-only or post-truncation replacement is insufficient. The default bounded
behavior remains unchanged. Configured proxy summaries with unresolved escapes are hidden.
Whitespace/nonprintable configured proxy keys also hide new details because normalization can
change the credential itself. The existing credential is not modified or rejected for execution.

Existing ModelRouteAttempt and DeliveryInvocationOutcome persist the safe AgentResult through
their ordinary immutable writes/reopens, with no new Schema/database field. Python
`team_view.blocker_text._role_failure` and JavaScript `humanizeBlockingText` decode only a JSON
string marker, bound the text and preserve old Run/hash explanations. Rendering uses text nodes.
Other model-call cards still show their existing fields; this is the blocking-detail boundary.

### Validation / error matrix

| Input | Required output |
| --- | --- |
| Complete main unknown native error | Bounded safe detail, original nontransient classification |
| JSON error.message/message with prompt/debug siblings | Message only, no sibling body |
| Proxy key, labeled credential, private key, URL or control bytes | Complete-value redaction before bounds |
| Missing configured proxy key, stdout/background, truncated/incomplete | Explicit detail unavailable |
| Dirty/timeout/authority abort | Existing hash-only policy behavior |
| Reopened route/outcome | Same safe message, original immutable hash/identity checks |
| Old hash-only blocker / invalid marker / HTML | Old behavior / refuse wrong marker / text-only display |

### Cases, tests and prevention

Good: the actual adapter failure reopens from route/outcome and its safe unknown main error is
visible in blocking detail. Base: old hash-only failures remain readable but no body is invented.
Bad: copy whole stderr or a JSON object, guess a missing cause, or let display text refund work.
Wrong: test only the selector and assume a persisted/UI message survives. Correct: real offline
native child → adapter → route/outcome reopen, plus Python/Node display regressions, complete
secret/truncation/provenance negatives and unchanged classifier/privacy tests.

The historical K1 rc1 failures retained only stderr hashes. Neither this fix nor a restart can
recover those bodies. Preserve their exact records; load the tested code at an idle boundary,
then use a new exact same-Task PAUSE and separate RESUME only within remaining ordinary budget.
Future diagnostics establish only their own invocation's cause. No historical backfill or SQL
repair is needed; rollback preserves published messages/readers and every old failure/approval.
