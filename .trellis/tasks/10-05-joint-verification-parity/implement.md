# 实现与交接

## 目标与实现顺序

1. 通过共享原生 AcceptanceDesignMapping converter 对联合新设计做 publication admission，
   保持历史 schema/read/hash 不变；拒绝时回传中文精确验收 ID 与原因。
2. 从同批准、同 scope/preparation 的拒绝历史提取纠错义务，显式交给 Designer；跨知识等待和
   recheck 保留原测试层级、unit 与验收映射，有限重试不能靠弱化验证过关。
3. 对没有任何原生 Task/dispatch/candidate/accepted handoff 的历史拒绝定义只读 proof：
   核验完整父/子历史、真实失败 receipt、Product approval、DerivedStageInputs、context/input
   摘要和全部 scope 的既有干净源 baseline。不 prepare、创建或修复 proof 输入。
4. 普通公开 CONTINUE 在 Operation gate 与 journal lock 内重新核验，工程职责与预算准入通过
   才追加 DESIGNING successor。独立 Designer/Planner 修正后再走原生 NEW Task → Coder →
   QA → Reviewer；不重置终态 Task、不伪造 verdict、不退预算。
5. 修正 Host 与 Console 前置 status/reconcile 副作用：窄候选 checkpoint 的 status 纯读，
   完整 proof 在真正 Continue 时执行。普通恢复保持既有路径。

## 允许路径与所有权

后端实现和增量 tests 由 joint_verification_fix worker 负责；其他 worker 的前端、Schema 或
生产操作不在该 worker 的变更范围内。

- `src/ai_software_engineer/multi_directory/admission.py`
- `src/ai_software_engineer/multi_directory/verification_recovery.py`
- `src/ai_software_engineer/multi_directory/verification_recovery_production.py`
- `src/ai_software_engineer/multi_directory/service.py`
- `src/ai_software_engineer/multi_directory/production.py`
- `src/ai_software_engineer/multi_directory/store.py`
- `src/ai_software_engineer/manager/production_agents.py`
- `src/ai_software_engineer/manager/delivery.py`
- `src/ai_software_engineer/manager/production_host.py`
- `tests/manager/test_joint_verification_admission.py`
- `tests/manager/test_joint_verification_recovery.py`
- `.trellis/spec/core/multi-directory-delivery.md`
- `.trellis/tasks/10-05-joint-verification-parity/`

没有新增 persistent wire 字段或数据库 migration；新 proof/correction DTO 为内部 typed 契约。
历史 model validator 未加新 admission，不重写已有 artifact、journal、审批或预算。

## 验证命令

增量 pytest 命令与 165 passed 结果见 `verification.md`。静态检查针对上述九个源文件；
Ruff 另覆盖两个新增 tests。

```sh
.venv/bin/ruff check \
  src/ai_software_engineer/multi_directory/admission.py \
  src/ai_software_engineer/multi_directory/verification_recovery.py \
  src/ai_software_engineer/multi_directory/verification_recovery_production.py \
  src/ai_software_engineer/multi_directory/service.py \
  src/ai_software_engineer/multi_directory/production.py \
  src/ai_software_engineer/multi_directory/store.py \
  src/ai_software_engineer/manager/production_agents.py \
  src/ai_software_engineer/manager/delivery.py \
  src/ai_software_engineer/manager/production_host.py \
  tests/manager/test_joint_verification_admission.py \
  tests/manager/test_joint_verification_recovery.py

.venv/bin/mypy \
  src/ai_software_engineer/multi_directory/admission.py \
  src/ai_software_engineer/multi_directory/verification_recovery.py \
  src/ai_software_engineer/multi_directory/verification_recovery_production.py \
  src/ai_software_engineer/multi_directory/service.py \
  src/ai_software_engineer/multi_directory/production.py \
  src/ai_software_engineer/multi_directory/store.py \
  src/ai_software_engineer/manager/production_agents.py \
  src/ai_software_engineer/manager/delivery.py \
  src/ai_software_engineer/manager/production_host.py

git diff --check
```

## 发布、存量恢复与回滚点

代码已实现并通过增量验证，独立审查和生产处置由 root 完成；该 worker 不提交、不推送、
不重启服务、不操作生产需求。root 对真实 K1 的最终只读 proof 已通过，4401 Project 文件零写入。

发布前 root 必须确认平台 idle，使用可信服务脚本重建 Host，再提交绑定当前 checkpoint 的
公开 Continue Operation。服务重新验证，而不是依赖发布前 proof 直接修改事实。K1 的原
Product approval、旧设计/计划、failed receipts、source、范围和预算都保留；无需人工改库。

回滚点是本任务代码发布前的提交。在空闲时回滚代码，保留所有 immutable records；若新
successor 已发布且旧 Host 不支持，只能重新升级后恢复，不能删 successor 或批准旧弱设计。
本修复不授权自动 merge、生产部署或绕过独立 QA/Review，也不声称完成 K1 的业务交付。
