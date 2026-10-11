# 实现与验证

两个真实 builder 仅在 writable Coder/QA 的 system 消息调用同一
`_negative_credential_test_guidance`。规则要求独立合法动态 fixture/reference，并保留原负向
测试意图与已有非空未知/空值/过期断言（适用时）；未知 token 与有效 fixture token 分离。
禁止固定疑似凭证、编码/拼接规避、削弱断言、跳过测试或放宽 policy；无法合法构造时明确
报告 blocked reason。没有新 expiry 验收、wire/Schema/scanner/service/native 常量。

native 的既有消息序列化消费同一 PromptPayload。此事实由源码检查确认，本任务未调用真实
Codex、模型、生产 API、DB 或服务，也未读取/修改 K1 或 main 工作区。新 `.venv` 仅在隔离
worktree 内供本次 offline 测试使用。

## 增量验证

红测 `uv run --frozen --offline pytest -q tests/agents/test_negative_credential_prompt_guidance.py`：
**6 failed / 12 passed**，writable Coder/QA 在两种 builder 均缺 guidance，另外两项一致性测试
因缺 guidance 失败；readonly/其它角色边界既有行为通过。

最终 checks：

- `uv run --frozen --offline pytest -q tests/agents/test_negative_credential_prompt_guidance.py tests/agents/test_openai_compatible.py`
  — **43 passed**，其中 18 项新增 builder 契约。
- `uv run --frozen --offline ruff check src/ai_software_engineer/agents/openai_compatible.py tests/agents/test_negative_credential_prompt_guidance.py`
  — **All checks passed**。
- `uv run --frozen --offline ruff format --check src/ai_software_engineer/agents/openai_compatible.py tests/agents/test_negative_credential_prompt_guidance.py`
  — **2 files already formatted**。
- `uv run --frozen --offline mypy src/ai_software_engineer/agents/openai_compatible.py tests/agents/test_negative_credential_prompt_guidance.py`
  — **Success: no issues found in 2 source files**。
- `git diff --check` — **通过**。

按 before-dev/start/check/finish-work 读取现有规范并完成 scoped 验证。此仓库没有
`.trellis/scripts/get_context.py`，故手动按现有任务格式记录上下文、allowlist、契约与验收。
未运行全量 suite；独立 review 由 root 安排，Coder 不生成 QA/Review verdict，不自行 merge。

## 存量数据处置

本补丁只修改之后构造的 prompt，不影响持久化事实，因此无需迁移或改库，不能通过它直接
解除已有 capture 拒绝。现有受拒需求须按原授权流程继续：

1. 获当前维护授权的独立合法 fixture 修复保留原测试意图，并记录 `HumanActionEvent(MODIFY_TESTS)`
   与完整 before/after diff；不凭本指导扩大修改路径或审批。
2. 在原 Task lock/queue fence 下重新完整核验真实 worktree、HEAD/index、inventory、源码与 patch；
   缺 secret 检查、stop 事实或权限时仍停在当前等待，不造补丁或旧 outcome。
3. 在原需求使用对应公开的精确恢复入口重新处理，核验当前 disposition/source/checkpoint；
   若入口要求新的精确方案审批，仍由用户完成，后续执行取得新 claim。

## 风险与回滚

机器指导约束生成意图，不证明生成代码无秘密或已通过测试；原 scanner/capture/policy 与
独立 QA/Review 持续执法。若目标项目无法在原权限内合法构造 fixture，应 blocked，不移除
测试或绕过检查。回滚本次 helper、调用点、测试与文档即可；保留所有历史事实。
