# 验证与交付记录

## 根因与最小变更

恢复源每轮都需要重新核验退休父需求与当前父子归属，但原实现把同一完整prefix分别交给
`current → history → parent current`读取。大型旧需求使一次facts检查出现大量重复解码、
深拷贝和文件读取；这与Agent是否真的在执行是不同事实。

`RequirementRetirementStore.require_native_active`现逐条完整读取退休history，用它的latest
执行与普通退休列表共用的exact digest/owner校验，检查完整历史child后立即释放非latest
深拷贝；再检查全部replacement引用，最后才能抛Retired。这样早期命中不能遮住后续损坏，
replacement本身退休且ID顺序不同也无需重读完整prefix。

恢复私有reader只保留本次观测已验证的latest。活动父需求/未退休replacement仍由
`JointJournal.current`只深拷贝最新一条，完整history不被缓存。初次native gate与_parent
都先做bounded regular-file/symlink preflight，避免FIFO在先行read_bytes永久阻塞。
底层Journal复用原有bounded exact-bytes/predecessor验证缓存，但每个新观测重读全部字节。

双重Source/Facts观测、前后_parent、Git/worktree检查、状态/Schema/审批全部保持原有边界。
测试中的旧`target_facts`fake补齐上次恢复授权改造已要求的workspace.project身份；未放宽
生产授权或修改真实entry逻辑。

## 红灯

实现前执行：

```sh
.venv/bin/pytest -q tests/recovery/test_history_reuse.py
```

`3 failed, 5 passed in 1.12s`。真实临时numbered JSON的`Path.read_bytes`计数：初次退休
检查每份2次、_parent每份3次、新tail/退休后的拒绝路径每份2次，期望均为1次journal读取。
已有完整历史child归属、下次观察篡改/缺失/symlink/FIFO拒绝保持正确。

## 绿灯

最终独立回归：`19 passed in 1.79s`。

- 每份退休history一次journal读取；parent保留一次bounded preflight。
- 未退休父需求32+条history，暖/冷读取每次只deepcopy最新1条。
- 历史child、退休replacement链两种ID排序、同size/mtime篡改、缺初始、symlink/FIFO。
- weakref证明下一退休prefix读取前，上一个完整prefix的非latest返回拷贝已释放。
- 已匹配退休child仍须拒绝后续错误digest、缺失或跨Project replacement。
- 新tail/退休在下一观察可见，公开journal返回嵌套修改不能污染后续事实。

相关非MySQL回归命令：

```sh
.venv/bin/pytest -q -m 'not mysql' \
  tests/recovery/test_history_reuse.py \
  tests/manager/test_requirement_retirement.py \
  tests/manager/test_requirement_deletion.py \
  tests/manager/test_joint_journal_read_reuse.py \
  tests/multi_directory/test_current_journal_copy.py \
  tests/recovery/test_native.py \
  tests/recovery/test_terminal_source_inspection_scope.py \
  tests/recovery/test_preparation_inspection_scope.py
```

最终结果：`88 passed, 10 deselected in 51.97s`。前一轮同组（新回归当时10条）为
`79 passed, 10 deselected in 51.67s`。

静态检查：生产两个文件strict mypy通过；两个相关测试以`--follow-imports=silent`检查通过；
Ruff check/format以及`git diff --check`通过。未静默模式会报告旧导入fixture中6处
`JointBackend.verify_unstarted_design_rejection`缺失类型错误，本任务未修改这些旧fixture。
未运行全量、MySQL或生产性能probe；实际生产耗时改善须由主代理在串行新鲜观测中核实。

独立只读review已确认无待改项。实际静态命令：

```sh
MYPYPATH=src .venv/bin/mypy \
  src/ai_software_engineer/recovery/native.py \
  src/ai_software_engineer/multi_directory/retirement.py
MYPYPATH=src .venv/bin/mypy --follow-imports=silent \
  tests/recovery/test_history_reuse.py \
  tests/recovery/test_terminal_source_inspection_scope.py
.venv/bin/ruff check \
  src/ai_software_engineer/recovery/native.py \
  src/ai_software_engineer/multi_directory/retirement.py \
  tests/recovery/test_history_reuse.py \
  tests/recovery/test_terminal_source_inspection_scope.py
.venv/bin/ruff format --check \
  src/ai_software_engineer/recovery/native.py \
  src/ai_software_engineer/multi_directory/retirement.py \
  tests/recovery/test_history_reuse.py \
  tests/recovery/test_terminal_source_inspection_scope.py
git diff --check
```

## 存量数据处置与回滚

没有SQL/journal/Operation/Task/Requirement/审批/工作区写入，没有重启ASE或消费审批。
当前线上恢复仍由原服务执行，本次源码不会热加载。修复加载应在操作空闲后由受控服务流程
执行，继续同一原需求。回滚本次reader/只读退休校验重排即可恢复旧读取行为；历史完整性和
所有工程授权保持不变。
