# ADR-0001：使用 Python 构建控制平面

- 状态：Accepted
- 决策日期：2026-08-31
- 适用范围：Orchestrator、状态机、Context Builder、Artifact Store、Agent Adapter、CLI、evaluation

## 背景

本项目不是一次性 Demo，而是一个持续进化的 AI 软件工程组织。初始语言必须同时支持快速验证 Agent 协议、严格表达跨角色契约、可靠运行本地进程，并为未来替换模型、增加服务端和拆分安全执行器保留边界。

系统当前瓶颈主要来自模型调用、目标项目编译/测试和 Git 操作，不来自控制平面的 CPU 计算。

## 决策

控制平面采用 **Python 3.12+**。核心领域模型使用强类型和显式接口；跨进程、跨语言边界使用版本化 JSON Schema。目标项目语言保持完全无关，平台必须能编排 Java、C++、Go、TypeScript、Python 等项目自己的构建与测试命令。

第一阶段保持单进程、串行 `Coder → QA → Reviewer`。只有观测数据证明现有方案不足时，才增加并发、服务化或其他语言组件。

## 为什么适合长期建设

Python 的价值不只是“写得快”，而是能以较低成本持续实验 Context、Prompt、evaluation 和 Agent 协议，同时用 Pydantic、JSON Schema、类型检查、contract tests 和不可变 artifact 建立工程约束。

长期可维护性来自以下约束，而不是来自语言口号：

- 领域层不直接依赖具体模型 SDK、Git 实现或数据库；
- 所有外部能力通过 `AgentAdapter`、`ArtifactStore`、`TaskRepository`、`GitWorkspace` 等端口进入；
- 状态迁移由纯 reducer/guard 表达并可以完整回放；
- 禁止未类型化 dict 在层间传播；
- JSON Schema 是跨语言协议的权威来源；
- 测试先覆盖 contract、权限、恢复和失败路径，再接真实模型。

## 考虑过的方案

- **Java**：企业工程和长期服务化能力强，但当前会增加契约试验和 CLI MVP 的实现成本。未来可作为服务端实现候选。
- **Go**：适合单文件 CLI、进程管理和并发；协议稳定后可用于远程执行节点。
- **Rust**：适合未来的高安全 sandbox/executor；不作为第一版控制平面。
- **C++**：控制平面没有足够的 CPU 性能收益，不抵消内存安全、生态和开发成本。

## 演进边界

Python 是当前控制平面的正式语言，但不是永久禁止其他语言。满足以下条件之一时，可以通过 ADR 引入专用组件：

1. 基准数据证明 Python 控制平面成为可观测的性能瓶颈；
2. 需要 OS 级资源隔离、系统调用控制或更强的内存安全；
3. 需要跨平台单文件远程执行器；
4. 企业部署要求必须集成特定 JVM/Go 基础设施。

引入其他语言时必须保留 Task、Agent、Artifact、Context Manifest 和 State Event 协议，不允许把既有契约改成某种语言的私有对象。

## 后果

正面结果：更快验证核心协议、成熟 AI/evaluation 生态、较低的 CLI 和测试成本、易于编写 fake adapters。

需要主动控制的风险：动态类型漂移、随意使用 dict、同步 I/O 阻塞、依赖膨胀和脚本式结构。对应措施是严格类型检查、分层端口、依赖锁定、contract tests、结构化并发前置评估和 CI 门禁。
