# T029 PRD：Project Preparation 与 Project Manager Agent Skills

## Goal

让 Project Manager Agent 只接收一个绝对项目目录，即可通过 `prepare_project` Skill 完成项目注册、
外置 sidecar、ProjectProfile、organization binding 和 project-level spec baseline，并返回可重放的
ProjectPreparation。用户不需要手工组装 Runtime paths。

## Requirements

- 定义 typed `PrepareProjectRequest/Result` 与 `ProjectManagerSkill` Protocol；Skill 是受控 facade，
  Agent 不直接持有 registry/profile/spec/binding stores；
- baseline 只编译 platform + project rules，必须至少包含 hard safety；不伪造 Task constraints；
- baseline conflict 产生 project-scoped WAITING_HUMAN record，不启动 Product Agent；
- exact request replay 返回首次 ProjectPreparation；项目事实漂移或同 identity 改输入 fail closed；
- 目标项目目录保持干净，全部记录写入 organization workspace 或 project sidecar；
- `advance_stage` 只接受已验证 stage chain，不直接修改 Artifact/verdict。

## Acceptance Criteria

- [ ] fixture Python/Java/C++ 项目只给目录即可得到 Schema-valid ProjectPreparation；
- [ ] 项目规范冲突、workspace overlap、profile drift 和 binding corruption 均返回 typed error；
- [ ] replay 不重复创建身份、不覆盖首次记录；
- [ ] Product Agent 在 PREPARED 前无法获得 Context；
- [ ] full quality gates 通过。

## Out of Scope

- Product Agent 对话、concrete Assignment、CLI 交互循环、后台 daemon。
