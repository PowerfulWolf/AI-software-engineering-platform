# T029 Design

`prepare_project` 是 Project Manager Agent Skill；内部组合现有 Registry、ProjectProfile、
RuntimeWorkspaceBinder 与新增 project-baseline compiler。Skill 返回 typed result/WAITING_HUMAN，
不把内部 ports 暴露给 Agent。ProjectPreparation 是成功 checkpoint，Product Agent 只能消费该记录。
