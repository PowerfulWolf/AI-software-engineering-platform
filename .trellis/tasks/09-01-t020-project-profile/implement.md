# T020 实现记录

## Changes

- 新增 immutable `ProjectProfile`，只读发现 Python、Java、Go、TypeScript、C++ 与多种构建系统；
- 读取项目根内 Git HEAD/ref/revision，不执行 Git 命令；无法安全读取的 worktree revision 保持
  `unknown`；
- 发现 AGENTS、CONTRIBUTING、README、EditorConfig、CI 和 `.trellis/spec`，只输出
  project-relative URI、类别、字节数与 SHA-256；
- Profile identity 排除 `observed_at`，同一项目事实可稳定重放，并提供显式 integrity 校验；
- symlink escape、非法 UTF-8、VCS 元数据矛盾和 revision mismatch 全部 fail closed；
- 新增 canonical `project-profile.schema.json`，目标项目目录零写入。

## Verification

- ProjectProfile 定向测试：8 passed；
- 合并 T019 后全量测试：324 passed；
- Schema parse/validation、Ruff lint、format、strict Mypy、offline build 与
  `git diff --check` 通过。
