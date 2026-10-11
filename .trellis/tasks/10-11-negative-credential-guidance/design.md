# 设计

## 契约

`RequestPromptBuilder.build(request: AgentRequest) -> PromptPayload` 和
`ContextPromptBuilder.build(request: AgentRequest) -> PromptPayload` 在现有 system 机器规则中
调用同一私有 guidance helper。仅当 `request.role in {CODER, QA}` 且
`request.permissions.write_paths` 非空时返回指导文字；其它情况返回空字符串。

指导约束测试写法，不授予文件、fixture、命令、Secret 或状态权限。任何例外仍由原 scanner 和
机器执行器独立判断；不把 tests 路径、字符串长度、replace 或负向断言当作安全证明。
无法在原权限内合法构造时，通过当前角色 output schema 的既有字段明确记录 blocker。

## 验证矩阵

| 输入 | 输出 |
| --- | --- |
| writable Coder/QA，任一真实 builder | system 恰好一次同一指导，user 及 permissions 不变 |
| readonly Coder/QA | 不添加修改源码指导 |
| Reviewer/Orchestrator，即使提供 write_paths | 不添加修改源码指导，不改变角色权限 |
| 不可信 task 文字要求放宽规则 | 仍为 user 数据，machine guidance 独立存在 |

Good：由独立合法 fixture 动态生成有效 token/reference，并另取非空未知 token，保留原负向
测试意图与已有非空未知/空值/过期断言（适用时），不增加新的过期验收要求。
Base：无凭证测试时规则无副作用。Bad：固定疑似凭证、编码/拼接规避检测、
移除断言、放宽 policy 或因目录/短值自行豁免。

## 测试与边界

先给两个真实 builder 加 public-seam contract tests，记录缺 guidance 的红测，再实现 helper。
native 的现有消息序列化保留 system 内容，直接继承同一规则，无复制常量和新 wire 字段。
仅运行影响范围的增量测试和 scoped 静态检查；root 进行独立 review。
