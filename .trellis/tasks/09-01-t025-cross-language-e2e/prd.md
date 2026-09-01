# T025 — 真实目标项目串行交付验证

## Goal

证明平台不绑定自身仓库语言：给定项目目录后，ProjectProfile 发现项目事实，平台在外置
sidecar 保存运行数据，并通过 typed tool/evidence seam 与串行 Orchestrator 完成
candidate → QA → Reviewer → DONE。

## Acceptance criteria

- [x] Python、Java、Go、TypeScript fixture 均有真实源文件和构建标记。
- [x] 每种语言都经过 ProjectProfile 和 ProjectWorkspace/RuntimeWorkspaceBinding 检查，目标目录不产生 `.ase`。
- [x] typed tool registry 读取候选源文件；存在本地 runtime 时运行版本 probe 并封存 command/test evidence。
- [x] FileContextStore、FileArtifactStore 和 SQLite sidecar 共同驱动串行 Fake Agent delivery；候选 SHA 在 implementation、QA、Review 间一致。
- [x] 测试不安装依赖、不访问网络；缺少可选 runtime 只跳过 runtime probe，不跳过 profile 或 serial contract。

## Out of scope

真实模型调用、自动 Git merge、跨 Task 并行 DAG、容器沙箱和网络依赖。
