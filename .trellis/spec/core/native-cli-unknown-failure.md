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
