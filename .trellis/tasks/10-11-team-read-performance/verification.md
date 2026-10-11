# 集成验证与部署状态

## 已验证的改动

后端snapshot-local typed ledger复用减少同次观察重复读取；不缓存Task/授权结论或跨请求快照。所有历史完整，独立原始引用与逐Task范围/intent/policy仍校验。总优化预算超限时回到完整重读。

前端整轮完成后才安排自动更新；busy/timeout有界退避；显式导航与刷新及时受理；恢复准备独立读取。普通Task“最近交付记录”与实时心跳分别表述。

## 增量测试

Root在隔离worktree执行：

```sh
uv run pytest -q --tb=short tests/team_view/test_engineering_snapshot.py \
  tests/team_view/test_engineering_history.py tests/team_view/test_task_read_snapshot.py \
  tests/team_view/test_baseline_snapshot.py
# 66 passed in 118.18s
uv run pytest -q --tb=short tests/web_console/test_transport.py -k 'snapshot or busy or cancel'
# 8 passed, 32 deselected in 3.16s
uv run pytest -q --tb=short \
  tests/team_view/test_live.py::test_retired_requirement_is_hidden_and_excluded_from_project_count \
  tests/team_view/test_deleted_verifications.py tests/team_view/test_joint_history_snapshot.py
# 13 passed in 14.36s; retired/replacement visibility, identity isolation and fresh-history revalidation
uv run ruff check src/ai_software_engineer/team_view/engineering_history.py \
  src/ai_software_engineer/team_view/reader.py tests/team_view/test_engineering_snapshot.py \
  tests/team_view/test_baseline_snapshot.py
# All checks passed
uv run mypy <同上四个文件>
# Success: no issues found in 4 source files
git diff --check
```

Worker验证109个不同DOM用例、22个真实Chrome用例，详情见ui-verification.md；后端红绿与容量/范围/返回隔离/释放反例见backend-verification.md。数量有重叠，不合计。未运行全量测试。

独立只读review已复核完整diff、契约和新增测试，未发现阻断；另独立fixture验证容量overflow仍拒绝后来篡改、异常后snapshot弱引用存活0/3。

## 性能证据与限制

完整真实Team GET曾成功返回200：6.211秒 / 2,585,681 bytes / 2需求 / 25任务，观察时间09:20:40 UTC。这排除了当时永久持锁，也证实首次完整读仍慢。

本轮工作量回归严格验证：同Task不同presentation proof6→4次、handling4→2次；双Task store30→18次，完整timeline和独立引用保留。

同一只读harness在两个独立fresh进程串行运行，旧7.112秒、新8.058秒，数字完整见read-profile.json。未修改Joint history及baseline成本有明显差异；仅能证实重复工作减少，不能宣称总延迟改善或稳定低于5秒。此前有pytest竞争的7.827秒样本与误并行的10秒样本不用于比较。

## 页面核验

真实用户浏览器连接因本地CUA auth不可用未能直接访问。改用已取得的脱敏生产wire在完全拦截HTTP的隔离Chrome回放：实现节点蓝色、产品/设计/计划绿色，QA/Review未冒充执行；K1当前执行与心跳一致，旧历史不覆盖状态。Root已目视两张截图。回放零POST/零外部请求，只证明09:20:40观察时间的呈现，不冒充部署后实时验收。

## 存量数据处置

无需改库、迁移、新建需求或重置Task。没有改动生产SQL、Journal、审批、工作区或历史报告。K1第5轮真实结果已由平台封存，现自动进入同Task第6轮；本修复不介入其状态与预算。

## 当前部署状态与回滚

当前K1 Operation/claim仍活跃，生产继续运行已部署fa85a65；本修复暂只保存于隔离分支，等待全部真实执行空闲后受控部署。主checkout与目标Coder工作区没有被本任务修改。

回滚本分支代码恢复原重复读取和刷新节奏，不回滚任何交付事实。全局worker锁、多Project隔离、精确审批、独立QA/Review保持；多页面并发仍可能遇到明确busy等待。大型完整历史与基线的读取成本仍待后续独立优化，当前需求尚未QA/Review通过。
