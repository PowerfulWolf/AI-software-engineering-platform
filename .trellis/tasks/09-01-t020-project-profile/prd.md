# T020 — ProjectProfile 与项目原生规范发现

## Goal

给定任意本地项目目录，使用只读、可重放的探测生成 `ProjectProfile`：识别项目语言、构建系统、
VCS、测试入口和项目原生规范来源，并以 URI/hash 保存事实。未知信息不猜测；与平台规范的冲突
交给后续 T021 `SpecCompiler` 和人工处理。

## Requirements

- 实现 typed `ProjectProfile` 和 canonical JSON Schema；
- 只读探测目标目录，不创建 `.ase`、sidecar 文件或修改项目内容；
- 识别常见 Python/Java/Go/TypeScript/C++ 项目标记，并保留 unknown 状态；
- 识别 Git（以及明确的 unknown/unsupported VCS），记录 revision/ref；
- 发现 `AGENTS.md`、`CONTRIBUTING*`、README、`.editorconfig`、CI 配置和项目 `.trellis/spec/` 等 native rules；
- 每个发现来源记录 URI、类型、内容 SHA-256、相对路径和确定性排序；
- 探测失败、路径越界、非法编码和不一致事实 fail closed；
- 不把项目规范解释成平台授权，不在本任务实现 SpecCompiler 或人工 resolution。

## Acceptance Criteria

- [ ] 同一目录和同一 revision 重复探测得到相同 profile/hash；
- [ ] 空目录、未知语言和无 VCS 项目返回显式 unknown，而不是猜测；
- [ ] 多语言/多构建标记全部保留，不能任意选择一个“主语言”；
- [ ] native rule 来源 URI/hash 稳定、排序稳定且不泄露绝对路径；
- [ ] 目标目录没有任何写入，symlink/path escape 和非 UTF-8 规则文件按策略拒绝或记录稳定错误；
- [ ] Python ↔ JSON Schema、全量测试、Ruff、strict Mypy 和 build 通过。

## Out of Scope

规范优先级合并、冲突 resolution、Runtime 自动绑定、依赖安装、构建执行和跨仓库扫描。

## Rollback

回滚 T020 提交即可移除 ProjectProfile discovery，不影响 T017 sidecar manifest 和 T018 Workforce。
