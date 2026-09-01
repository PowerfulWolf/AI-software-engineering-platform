# T020 Design

## Boundaries

```text
project_root (read-only)
        │ deterministic detectors
        ▼
ProjectProfile + NativeRuleSource[]
        │ URI/hash facts only
        ▼
T021 SpecCompiler → SPEC_CONFLICT / WAITING_HUMAN
```

Profile 描述观察到的事实，不做规范语义合并；探测器不执行项目命令、不安装依赖、不修改目标
项目。绝对路径只作为输入边界，wire profile 使用稳定 project-relative URI。

## Files owned by this task

- `src/ai_software_engineer/project_profile.py`；
- `schemas/project-profile.schema.json`；
- `tests/project_profile/**`；
- 本 task 的 `.trellis/tasks/**` 记录。

共享文档与 T017/T018 记录由 root 统一更新。

## Determinism

探测器使用声明的文件名/目录标记、排序后的路径和显式 `observed_at`/revision 输入。Profile
identity 排除观察时间，只由项目 ID、revision、detector version、facts 和 rule hashes 计算。
