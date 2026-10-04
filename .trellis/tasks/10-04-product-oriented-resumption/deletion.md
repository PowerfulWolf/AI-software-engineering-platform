# 需求删除子任务

## 既有实现与发现

已存在正式 Console `DELETE_REQUIREMENT` -> Manager -> `DeleteRequirement` ->
`RequirementRetirementStore`；BLOCKED/CLOSED 可删，reader已有退役父子过滤。
因此复用此入口，不新增手工删除脚本/SQL或第二套HTTP命令。

先测复现两个缺陷：相同exact delete再次执行被 `_current` 的 retired guard拒绝；
同名同scope create 会在 `_intake` 调用 restore，复活旧BLOCKED及原批准。
新回归先红后绿。存量记录没有改写。

## 修改

- `multi_directory/service.py`：精确Project/checkpoint验证后允许deleted命令幂等重放；
  replaced拒绝。同名新建从旧tombstone派生新ID，当前新ID仍幂等，不restore旧记录。
- `multi_directory/deletion.py`：typed guard，遍历全部parent/native子交付历史；持有现有
  queue-worker task locks到tombstone落盘，核对所有历史Task terminal、全部queueCLOSED、
  无有效lease。使用只读SQL查询Task，不构造Task writer/不DDL。零代码/现场清理。
- `production_host.py` 仅注入guard；Console manager将活动拒绝显示为`REQUIREMENT_ACTIVE`
  中文说明，删除成功提示也中文。
- 更新已有multi-directory删除契约、增加专用requirement-deletion spec/index。
  wire字段没有改变，`requirement-retirement.schema.json`历史digest保持兼容。
- 最后扩展ownership完成原生child guard：`retirement.require_native_active`共享所有退役父的
  child历史和确定性派生identity核验；Host native Continue进入controller前拒绝；Native source
  在SQL前拒绝且`_parent`不降为standalone。该shared `_parent`还覆盖Candidate验证及preexecution
  restart的source检查。删除/替换原因使用typed中文`RequirementRetiredError`。
  UIworker负责完整派生过滤。

## 增量验证

```sh
.venv/bin/pytest -q tests/manager/test_requirement_retirement.py tests/manager/test_requirement_deletion.py tests/web_console/test_requirement_deletion_entry.py tests/web_console/test_manager.py -m 'not mysql'
```

结果74 passed / 3 deselected；含真实flock、历史Task inventory、lease/queue拒绝、精确幂等、
新identity、crossProject拒绝，以及HTTP -> Operation -> Manager -> service -> reader真实路径。
HTTP用例验证隐藏requests/tasks/count、exact重放、deleted Continue/ProductApproval/Restart
全部拒绝且零modelcalls、Operation审计和原历史/tombstone字节不变、原Schema通过。

4个生产文件mypy通过，3个测试文件follow-imports=silent mypy通过，变更Ruff通过。
最初单独跑3个隔离MySQL用例通过，但可能与UIworker共享测试库reset并发，**不以这次结果
作为最终串行发布验证**；root接管全部后续MySQL串行执行。
不得运行全量测试。

最终非MySQL增量命令（包含上述native绕过补充）：

```sh
.venv/bin/pytest -q tests/manager/test_requirement_retirement.py tests/manager/test_requirement_deletion.py tests/web_console/test_requirement_deletion_entry.py tests/web_console/test_manager.py tests/manager/test_team_host.py tests/recovery/test_joint_resume.py -m 'not mysql'
```

96 passed / 3 deselected in 4.71s。6个生产文件标准mypy通过；3个测试文件mypy通过；
Ruff、format、diffcheck通过。未发起任何真实模型调用或修改生产。

## 存量处置与回滚

本子agent没有生产写API、SQL、重启或实际删除。root在发布空闲版本后，对两份精确K1
project/id/checkpoint提交正式DELETE_REQUIREMENT Operation，并核对原历史hash、退役
列表/详情/子task/agentqueue一致、不新建模型调用。如guard发现open queue或livelease，
需要现有正式队列停止/过期reap路径；不能改SQL冒充CLOSED。

回滚必须保留tombstone且暂停旧版本create，防止旧restore逻辑复活需求。代码可revert，
不可用rollback取消用户删除，也不可移除dirty worktree。
