# 增量验证

## Red 与 Green

先添加 11 项回归，在旧 adapter 上得到 9 failed / 2 passed：工具变量、当前源码绑定和明确缺失
说明均未提供。flat 布局的 baseline Python 探针还生成未跟踪 bytecode，已让探针禁用 bytecode，
避免 fixture 自身制造非本次需求的 dirty 前提。

最初新增测试的真实 Python fixture 复用测试进程现有依赖目录，不安装或下载依赖。
`editable-old-source.pth` 故意指向注册旧源码；src 布局 baseline 确实导入 `registered-old`，
受控派生环境后 Python 和真实 pytest 的 `__file__` 均为当前工作树。flat 布局也验证同一结果。

```text
.venv/bin/pytest -q tests/agents/test_native_python_tooling.py tests/agents/test_codex_cli.py
55 passed in 9.77s

.venv/bin/ruff check src/ai_software_engineer/agents/codex_cli.py tests/agents/test_native_python_tooling.py
All checks passed!

.venv/bin/ruff format --check src/ai_software_engineer/agents/codex_cli.py tests/agents/test_native_python_tooling.py
2 files already formatted

.venv/bin/mypy --strict src/ai_software_engineer/agents/codex_cli.py tests/agents/test_native_python_tooling.py
Success: no issues found in 2 source files

git diff --check
passed
```

## 独立审查发现与第二轮修复

独立 reviewer 用合法执行型 `.pth` 的 `import sys; sys.path.insert(0, registered/src)`
实际证明旧方案的 PYTHONPATH 可以被覆盖。新增真实反例在旧绑定上失败；未将这个问题排除出
源码绑定契约。随后改为 manager 私有固定 `-I -S -B` bootstrap，而不是删除 `.pth` 或安装环境。
原注册 Python、pytest 和依赖环境只读复用。真实 fixture 只复制本测试环境的少量已安装pytest
依赖字节，不安装/下载；所有旧 `.pth` 保留不变。

新回归同时覆盖 src/flat、普通pth、执行型pth、标准 `_virtualenv.pth` 形态及 sitecustomize。
正常 Python startup 的对照能导入旧 checkout；两个 private launcher 及 Python `-m pytest`
都实际导入当前 `__file__`，不会执行 `.pth`/sitecustomize。仅有普通 Python路径之外的解释器
或没有唯一安全依赖根时不提供任何工具，不进行fallback安装。

本机生产注册环境只读前提核对：直接普通可执行 Python/pytest 均可用，依赖根恰为1个。
私有固定bootstrap仅执行 `import pytest` 的工具可用性检查，返回0，版本9.1.1；没有运行业务
测试、生产模型或ASE操作，没有读取私有调用/凭据，也没有修改注册环境。

第二轮最终增量（包含 Python `-m pytest` 同路径和外部脚本拒绝）：

```text
.venv/bin/pytest -q tests/agents/test_native_python_tooling.py tests/agents/test_codex_cli.py
66 passed in 20.62s
```

## 边界核对

- 新 22 项包含真实 linked worktree、Python/pytest import、symlink/nonexec工具拒绝、完整
  startup隔离、Python/非Python missing行为及 ignored `.venv/.gitignore` 的实际拒绝。
  quoted路径/参数不shell展开，错误cwd、startupflags及外部脚本拒绝；运行中启动器有效，
  正常/异常返回均清理其临时文件。
- 原 Native adapter 44 项保持通过，包括 QA runner、verifier command 禁用、policy、candidate、
  续跑和真实停止。未扩大 mutation cache、角色权限、Schema、状态机或恢复授权。
- `before-dev`、`check` 指定的 `.trellis/scripts/get_context.py` 不存在。已按实际 core/guides
  indexes 手动阅读架构、权限、Python runtime、production Host、continuation 和环境验证契约。
- 尚待独立 reviewer。无生产 ASE 操作、模型调用、重启、改库、文件清理或提交；未跑全量测试。

## 独立临时工具目录的真实 sandbox 修复

维护审查发现新的隔离缺口：`workspace-write` 默认允许 Host TMPDIR；工具即使0700/0600，
同 UID 模型进程仍可改写其 bootstrap。已获准只在测试自有目录执行真实、无模型 OS 探针，
不触及 ASE、真实需求或工作区。

真实 Red 测试先用本机 Codex `sandbox -P :workspace` 实际改写临时工具哨兵，再要求 adapter
提供精确 profile；旧实现因没有 `permissions.ase_coder_tooling` 失败。没有把 chmod 或
prompt 承诺当作隔离。Green 把工具目录与 output/scratch 分离：完整新profile extends
`:read-only`，只授权当前 worktree 与独立 run root，工具和注册 `.venv` 明确只读。采用
default_permissions，不混 legacy `--sandbox`；Host TMPDIR/UV_CACHE_DIR 换成run私有目录。

同一实际 Native profile 的 Python探针通过：bootstrap/python/pytest 的 write、unlink、
replace 和经工作区symlink写入、工具目录rename、`.git`写入共14项全部 PermissionError；
实际导入 current candidate 的 `__file__`，合法source写入与private scratch写入同时可用。
原工具bytes未变。常规回归还核对正常/异常返回均清理两个目录，以及Host temp/cache不扩权。

```text
ASE_RUN_SANDBOX_TESTS=1 \
ASE_TEST_CODEX_EXECUTABLE=/Users/zhangjunshuai/.local/bin/codex \
.venv/bin/pytest -q tests/agents/test_native_python_tooling.py tests/agents/test_codex_cli.py --tb=short
67 passed in 23.59s

.venv/bin/ruff check src/ai_software_engineer/agents/codex_cli.py tests/agents/test_native_python_tooling.py
All checks passed!

.venv/bin/ruff format --check src/ai_software_engineer/agents/codex_cli.py tests/agents/test_native_python_tooling.py
2 files already formatted

.venv/bin/mypy --strict src/ai_software_engineer/agents/codex_cli.py tests/agents/test_native_python_tooling.py
Success: no issues found in 2 source files

git diff --check
passed
```

最后的Mypy修复仅为sandbox_arguments显式tuple[str, ...]注解。新profile要求支持当前Codex
permissions配置；不支持时CLI按既有失败路径拒绝，不退回更宽或无sandbox执行。

## Namespace 与工具预加载的独立审查闭环

独立reviewer真实复现了PEP420缺口：当前src/namespace_sample/app.py没有__init__.py时，
后续注册依赖的同名regular package可以覆盖source-first路径。新真实Red回归确认旧launcher
返回注册deps里的app.py并执行旧包初始化，而不是当前候选文件。

固定bootstrap现在在导入pytest之前安装metadata-only PathFinder guard。当前源码的
namespace/package/module若会被外部具体包/module替代，初始化前即拒绝；已缓存支持模块
也在用户代码开始前核对。该拒绝是源码归属前提未就绪，应如实NOT_RUN，不当作业务FAIL或
允许修复依赖。没有当前源码冲突的依赖与兼容namespace portions继续可用。

真实新增回归覆盖src/flat的同名外部regular package、module、nested namespace portion，
以及兼容namespace；Python与pytest都验证，冲突包sentinel不产生。工具预加载覆盖同名
current namespace/regular package的pluggy，以及外部namespace与current regular冲突；
pytest和Python -m pytest在旧依赖初始化前拒绝。缓存pathlib反例在用户程序开始前拒绝。

```text
ASE_RUN_SANDBOX_TESTS=1 ASE_TEST_CODEX_EXECUTABLE=/Users/zhangjunshuai/.local/bin/codex \
.venv/bin/pytest -q tests/agents/test_native_python_tooling.py tests/agents/test_codex_cli.py --tb=short
78 passed in 38.17s
```

最后追加的current-regular-vs-dependency-namespace边界只重跑新增focused cases，不重复已过大套：
`pytest -q tests/agents/test_native_python_tooling.py -k 'namespace or current_source_shadow'`
得到12 passed /17.07s。最终Ruff/format/strict Mypy/diffcheck通过。

独立reviewer `console_fixture_alignment` 最终复审通过，无阻断finding。它用独立真实临时
wrapper探针再次确认namespace+旧regular sentinel被拒绝且旧初始化未执行；current regular
pluggy在pytest和python-m-pytest入口都在工具导入时拒绝；普通current regular模块的__file__
正确，非冲突pytest --version成功。复审静态确认preload之前安装guard，current regular与
dependency namespace冲突拒绝。全部探针无生产/模型调用；未重复已过大套或全量测试。

## 存量与限制

没有 wire/store变化，不改库，不改现有需求。root负责精确保留旧现场后的公开恢复流程；
本实现不能使已有非法 `.venv` 获得接纳。工具只是已准备环境的只读发现，不等于 hash-bound
verifier capability。启动器拒绝处理任何 `.pth` 目录或执行脚本，不将它们纳入隐式信任。
候选自身明确导入的业务代码与pytest项目插件仍属于受控执行的待验证代码，不是platform verdict；
既有 sandbox、权限和最终完整inventory仍为执行边界。
回滚仅移除新增发现/prompt/env，不删除历史、draft、证据或恢复授权。
