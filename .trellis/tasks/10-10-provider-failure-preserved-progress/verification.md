# 验证记录

## 修复前临时诊断

真实临时Git和fake Codex runner，无生产/真实模型调用，无tracked改动：

- clean输入、无新修改：QUOTA_EXHAUSTED，transient=true。
- 合法accepted progress、无新修改：文件inventory/HEAD/diff/index/status全部相同，
  却返回POLICY_VIOLATION，transient=false，复现误判。
- 合法progress同路径正文/mode修改：文件inventory不同，但status/changed-path集合可相同。
- git add原脏文件：文件inventory相同但索引不同，必须拒绝。
- clean输入新增真正Git-ignored文件：旧实现status仍为空且允许transient，说明只看status漏检。
- index assume-unchanged标志变化：旧实现status/文件inventory不变且允许transient。

临时目录由TemporaryDirectory在诊断结束后自动清理。后续记录最小red→green回归和增量验证。

## 最小失败回归与修复

- Red：`.venv/bin/python -m pytest tests/agents/test_codex_failed_continuation.py -q
  --basetemp=/tmp/ase-provider-progress-red-20261010` → 1 failed/0.43s，期望
  QUOTA_EXHAUSTED但实际POLICY_VIOLATION。
- 最小修复后同文件 → 1 passed/0.47s。
- 最终专用测试：`.venv/bin/python -m pytest tests/agents/test_codex_failed_continuation.py -q
  --basetemp=/tmp/ase-provider-progress-final-extra-20261010` → **53 passed/10.24s**。

覆盖accepted progress、初始精确批准dirty seed、真实linked worktree、quota/rate/auth/signal/
timeout分类、same-Run与持久route replay、真实FallbackAgentAdapter可继续与禁止fallback的两面。
本轮正文/mode/delete/regular→symlink/真正ignored文件/HEAD/index stage/blob/mode/conflict/
assume-unchanged/skip-worktree/intent-to-add变化均拒绝，status相同或文件inventory相同不能绕过。
正常stat刷新和split-index存储变化保留等价语义；control的CAPTURED/PRESERVED/UNKNOWN优先。

独立snapshot在control.started之前完成。文件或索引观察前置失败时，provider和control.started
均零调用，不生成从未调用模型的CaptureStart；后置失败不允许transient/fallback。
索引固定只读Git stdout写匿名临时文件，stdin/stderr DEVNULL、禁hooks/fsmonitor、最小环境、
30秒timeout。真实临时文件oversize fixture在fstat处拒绝，未读取正文；timeout/启动失败/非零/
非UTF8均fail closed，不输出原始诊断。

## 关联增量与质量检查

- 新专用50例+`tests/agents/test_initial_admission_scope.py`：63 passed/12.10s；之后仅新增3个
  seed/fallback用例，完整专用文件已按上述命令再次通过。
- `.venv/bin/python -m pytest tests/agents/test_codex_cli.py tests/agents/test_fallback.py -q
  --basetemp=/tmp/ase-provider-progress-adjacent-20261010` → **59 passed/6.58s**。
- 独立reviewer检查专用/准入/共享mutation inventory → **66 passed/11.91s**，报告无剩余实质缺陷；
  其后新增3个seed/fallback测试，没有再修改生产代码。
- `.venv/bin/ruff check` 两变更Python文件通过，`ruff format --check`通过。
- `.venv/bin/mypy --strict src/ai_software_engineer/agents/codex_cli.py
  tests/agents/test_codex_failed_continuation.py` → 无错误。
- `git diff --check`通过。未跑全量测试，未调用真实模型，未操作生产或提交代码。

## 存量与回滚

不改已有失败Run/Task和现场，不追溯改判旧POLICY_VIOLATION、不审批或继续需求。root负责后续
部署和公开同Requirement恢复流程，保留已有进度及完整历史；此修复只影响新调用对本轮变化的
判定。空闲时回滚代码即可，保留所有已有记录。额外文件/index观察受既有文件限制和16MiB索引
限制，不形成跨Run缓存；其限制是最终状态比较，不能证明已写入又还原的历史瞬态操作。
