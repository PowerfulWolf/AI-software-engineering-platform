# T032 Design

CLI 只做输入/输出；所有阶段调用同一个 Project Manager Agent Skill facade。每次调用先读 durable
checkpoint 再决定下一阶段，确保重复提交与进程重启不会创建第二套 Project/Request/Task。
