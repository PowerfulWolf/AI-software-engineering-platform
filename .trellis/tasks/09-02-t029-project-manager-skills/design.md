# T029 Design

`prepare_project` 是 Project Manager Agent Skill；内部组合现有 Registry、ProjectProfile、
RuntimeWorkspaceBinder 与新增 project-baseline compiler。Skill 返回 typed result/WAITING_HUMAN，
不把内部 ports 暴露给 Agent。ProjectPreparation 是成功 checkpoint，Product Agent 只能消费该记录。

## Public boundary

```python
class ProjectManagerSkill(Protocol):
    def prepare_project(self, request: PrepareProjectRequest) -> PrepareProjectResult: ...
    def advance_stage(self, request: StageAdvanceRequest) -> StageAdvanceAuthorization: ...
```

`PrepareProjectRequest` 只包含绝对 `project_root`。organization identity、organization workspace、
sidecar registry、platform rules 和 clock 都是 Project Manager runtime 的受控依赖，不由调用方拼装。

`PrepareProjectResult` 是互斥结果：

- `PREPARED`：包含首次写入且完整性校验通过的 `ProjectPreparation`；
- `WAITING_HUMAN`：包含 project-scoped baseline conflicts，禁止构建 Product Agent Context；
- 基础设施损坏、profile drift、identity collision 等不是业务分支，抛出 typed fail-closed error。

## Ordered flow

```text
validate absolute project root
  -> register/reopen external sidecar
  -> discover current ProjectProfile
  -> bind organization + project + profile
  -> compile task-free project baseline
  -> persist conflict and return WAITING_HUMAN
     OR persist/replay ProjectPreparation and return PREPARED
```

baseline 只允许 `PLATFORM_HARD`、`PLATFORM_ENGINEERING`、`PROJECT` 规则。它复用 `SpecRule`
的 provenance contract，但拥有独立的 project-scoped result/conflict；不得构造临时 Task 或虚假的
acceptance criteria。所有 structured PROJECT rule 必须由当前 ProjectProfile 的 URI + digest 支持，
未结构化的项目规范只作为 opaque source 保留。

## Persistence and replay

- ProjectPreparation 位于 sidecar `policy/`，是 append-once checkpoint；
- 同一 project identity 和完全相同内容重放时返回首次记录，包括首次时间戳；
- 内容、digest、profile、binding 或 project identity 不同均 fail closed，不能覆盖；
- 写入采用 canonical JSON、临时文件、flush/fsync、atomic replace；
- 所有路径必须在 sidecar 内，target project 只读。

## Product Agent gate

后续 Context Builder 必须读取并验证 ProjectPreparation。没有 `PREPARED` checkpoint，或 checkpoint
与当前 binding/profile/baseline digest 不一致时，Product Agent 不可启动。`WAITING_HUMAN` 不是可忽略
warning，而是执行路由终点，直到人类解决 project-level 规范冲突并形成新的可验证 baseline。

`advance_stage` 是只读 guard：输入必须是从 `ProjectPreparation` 开始的精确 stage prefix，输出绑定
所有输入 digest 的 `StageAdvanceAuthorization`。它不更新 ProjectRequest、不写 Artifact、不创建
Assignment/Lease，也不修改 QA/Review verdict；实际持久化和 dispatch 仍由后续受控 Skills 完成。
