# 通用需求生命周期修复验证

实现基于 `1b6f204fb3a7fce67e7acf8068d8ba786be71f05`，该提交包含上一轮已独立审查的停止工程等待关闭修复。最终主干交付同时包含旧成果与本次通用需求关闭/删除、操作可见性和资源释放能力。K1始终暂停，不批准或继续交付；跟踪自动化保持PAUSED。

## 验证命令与结果

- Ruff check / format --check：17个变更Python文件通过。
- strict mypy --follow-imports=silent：17个变更Python文件通过。
- Python增量：`tests/git/test_resource_release.py`、`tests/web_console/{test_retired_operation_visibility,test_operation_summaries,test_requirement_deletion_entry}.py`、`tests/manager/{test_waiting_requirement_close,test_requirement_deletion,test_requirement_retirement,test_requirement_cancellation,test_requirement_resource_release,test_requirement_verifier_release}.py`：128 passed。
- 一次性隔离MySQL：`tests/manager/{test_requirement_deletion,test_requirement_cancellation,test_waiting_requirement_close,test_requirement_verifier_release,test_mysql_dispatch_authority}.py`及`tests/work_queue/test_requirement_queue_cancellation.py`：86 passed。使用独立`k1_cancel_root_test`，未连接生产数据库做测试。
- Node：`tests/team_view/{ui,waiting-requirement-close,team-summary-reading,operation-summary-reading,recovery-progress-summary}.test.cjs`：93 passed；`node --check app.js`通过。
- 真实Chrome：`tests/team_view/browser/{team-summary-reading,operation-summary-reading}.test.cjs`：11 passed，覆盖正文完整读取、精确Product批准、旧正文/错误提示、详情关闭、长历史与分页。
- `git diff --check`通过；新worktree-release-archive Schema等于Pydantic且真实封存记录通过Schema校验。

重点覆盖staged/unstaged/untracked/ignored/symlink完整保全、Git GC后stage blob与detached commit保留、隐藏index flags/新修改拒绝、未sealed压缩包重做、reset后重试、remove后completion中断正式CLOSE重放、CLOSE后tampered tar拒绝DELETE、历史及未attach原生Task锁、独立验证已释放/未释放/owner/source/path与真实dispatch fence竞争。

补充探索的旧readiness suite中“Team busy”用例在未修改的1b6f204 app.js同样失败并不退出；它不计入上述通过结果。已结束本轮确切测试进程，未修改无关readiness用例。临时MySQL容器由本次创建，完成验证后释放。

## 独立审查

Spec审查：独立只读Agent未发现剩余Spec问题；独立focused25 passed，MySQL由主代理使用隔离实例补验。
Standards审查：独立只读Agent未发现未解决标准问题；独立资源focused24 passed、1 MySQL项deselected。两位审查者均未改代码、生产数据或merge。

## 存量数据处置

旧K1已通过正式CLOSE/DELETE清理：6历史父身份退休、37 Task终态、89队列CLOSED、无active claim，30工作区完整保全释放、12旧隔离MySQL容器已不存在。本次不重放旧清理、不改SQL/journal/审批/预算。新K1停在WAITING_PRODUCT_APPROVAL（checkpoint bc40402d7b49e71bbfa0cac97044b2eed123484199c15606344a29023fa750cb）。日常Operation读取按retirement过滤，无需删除不可变审计。正式升级后再次只读检查这些状态及自动化PAUSED。

## 限制与回滚

资源保全支持普通受管Git工作区；nested Git/submodule、split-index、特殊文件、超过100000条/2GiB或单stage blob32MiB的工作区拒绝并保留现场，不能force-remove。活跃进程/许可或未释放独立验证须先停止。共享数据库、源码、候选branch/commit、artifact与审计保留；私密保全不提供产品归档功能。

回滚仅在空闲受控维护窗口，通过服务脚本回到兼容CLOSE receipt的已审查版本1b6f204。保留retirement、resource-archives、refs/ase/retained及所有历史；不重开已取消需求。可用新修复分支重新部署，不能解压覆盖主checkout。
