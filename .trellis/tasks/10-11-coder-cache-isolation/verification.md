# 验证记录（2026-10-11）

仅跑增量测试，没有全量test。解释器/工具来自主仓现有`.venv`，`PYTHONPATH=src`/
`MYPYPATH=src`绑定此独立checkout；不安装工具，不运行真实模型，不写生产环境。

## 增量回归

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src /Users/zhangjunshuai/workspace/code/AI-software-engineering-platform/.venv/bin/python -m pytest tests/agents/test_coder_cache_isolation.py -q -p no:cacheprovider
```

原实现：4 failed +4 passed（缺少 MYPY_CACHE_DIR，回归确实红）；实现后8 passed，10.70s。
实际mypy检查没有跳过，精简环境和伪造MYPY环境均使用私有scratch，源码inventory保持相同。
模拟超过16MB的私有缓存不进入源码现场；相同工作区源码/ignored缓存仍被原16MB门拒绝。

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src /Users/zhangjunshuai/workspace/code/AI-software-engineering-platform/.venv/bin/python -m pytest tests/agents/test_native_python_tooling.py -q -p no:cacheprovider
```

34 passed +1 opt-in skipped，50.01s。被默认跳过的真实sandbox测试随后单独显式运行：

```sh
ASE_RUN_SANDBOX_TESTS=1 ASE_TEST_CODEX_EXECUTABLE=/Users/zhangjunshuai/.local/bin/codex PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src /Users/zhangjunshuai/workspace/code/AI-software-engineering-platform/.venv/bin/python -m pytest tests/agents/test_native_python_tooling.py::test_real_native_sandbox_protects_tooling_and_keeps_source_and_scratch_writable -q -p no:cacheprovider
```

1 passed，5.88s；无模型，仅本地fixture的source/scratch写入和tooling/.git拒绝probe。

## 质量门

```sh
/Users/zhangjunshuai/workspace/code/AI-software-engineering-platform/.venv/bin/ruff check src/ai_software_engineer/agents/codex_cli.py tests/agents/test_coder_cache_isolation.py
/Users/zhangjunshuai/workspace/code/AI-software-engineering-platform/.venv/bin/ruff format --check src/ai_software_engineer/agents/codex_cli.py tests/agents/test_coder_cache_isolation.py
PYTHONDONTWRITEBYTECODE=1 MYPYPATH=src /Users/zhangjunshuai/workspace/code/AI-software-engineering-platform/.venv/bin/mypy --cache-dir /tmp/ase-coder-cache-typecheck-20261011 src/ai_software_engineer/agents/codex_cli.py tests/agents/test_coder_cache_isolation.py
git diff --check
```

Ruff/check、format、strict mypy（2 files）、diff检查通过。mypy自身缓存显式在外置/tmp。
签名搜索确认生产调用仅一个，已同步；不改git/mutation.py或任何wire Schema。
