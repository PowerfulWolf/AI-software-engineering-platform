# T015 设计

## Boundary

```text
Agent/QA application service
          │ tokenized argv + role permissions
          ▼
SubprocessCommandExecutor
          │ authorize_command + fixed cwd + minimal env
          ▼
       subprocess (shell=False)
          │
          ▼
      CommandResult / typed error
```

执行器只执行命令，不解释 exit code 是否满足 Task acceptance criteria，也不修改 Task、
Artifact 或 Evaluation 状态。上层必须将结果和日志转换为 evidence，并由 QA/Reviewer
Artifact 决定 verdict。

## Environment policy

默认环境固定为 `PATH`、`LANG=C`、`LC_ALL=C`，可选 `environment_allowlist` 只允许从注入
的环境映射复制指定 key。不会把 `os.environ` 整体传给子进程；缺失的显式 key 被忽略，
禁止把 key/value 写入异常消息。

## Output policy

stdout/stderr 各自最多保留 `max_output_bytes`，超出部分截断并记录 `truncated` 标志。
非零退出仍返回结果；只有无法启动和超时属于 executor errors。超时异常不携带命令输出。

## Good / Base / Bad

- Good：QA 在绑定 worktree 执行 `pytest -q`，拿到 returncode、截断日志和耗时，随后自行
  生成 evidence；
- Base：fixture 使用 Python 标准库短命令，无 Docker、shell 或网络依赖也能测试；
- Bad：`shell=True`、`"pytest " + user_input`、继承完整宿主环境或把 timeout 当 PASS。
