# T030 Design

Product Agent 只持有 project/read context 与 ProductSpec output Skill。人类 Approval 是独立入口，
不通过 AgentAdapter 伪造。Context 必须包含 exact ProjectPreparation、ProjectProfile/baseline 与当前
ProjectRequest decisions；每次新 ProductSpec version 都有独立 run/context/integrity lineage。
