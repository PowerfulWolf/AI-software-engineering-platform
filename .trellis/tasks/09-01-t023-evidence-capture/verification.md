# T023 Verification

## Automated checks

- `uv run pytest tests/evidence tests/contracts/test_json_schema_contracts.py -q` — 46 passed
- `uv run ruff check src/ai_software_engineer/evidence tests/evidence src/ai_software_engineer/redaction.py` — passed
- `uv run ruff format --check src/ai_software_engineer/evidence tests/evidence src/ai_software_engineer/redaction.py` — passed
- `uv run mypy src/ai_software_engineer/evidence src/ai_software_engineer/redaction.py src/ai_software_engineer/agents` — no issues

覆盖的安全与一致性事实：

1. argv、stdout、stderr、cwd、diff patch、Agent error 均在落盘前脱敏；输出和 patch 有 UTF-8
   byte 上限；
2. timeout、policy rejection、failed-to-start 先写 evidence，再重新抛出原异常，并可按同一
   operation replay；
3. evidence/manifest 使用 sha256 与 atomic write；同一 ID 的不同内容和篡改后的磁盘内容均被
   拒绝；
4. test evidence 只能引用同一 run 的 command evidence；AgentResult identity 不匹配时拒绝；
5. schema registry 能校验四种 evidence record 和 run manifest 的 wire payload。
