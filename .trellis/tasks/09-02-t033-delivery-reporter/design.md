# T033 Design

Reporter 是可选的 presentation role。优先复用 HandoffBuilder、Projection 与 deterministic renderer；
生成式 Reporter 只能作为 read-only formatter，并必须返回 source-addressable delivery report。
