# 静态恢复Schema重新生成守卫丢失

## 目标与范围

root 独立 review 发现 repair generator 刷新 Console Schema 后，Pydantic 未发射的旧 allOf
恢复安全守卫消失。定位为全量图生成只恢复 engineering guards，未复用现有 legacy canonical
guard function。修复 generator，恢复 HEAD 全部旧 guards 并共存本轮知识 retry guards。

仅 generator、Console Schema、定向 contract tests 与本 spec/task。所有其他 Schema 冻结，
不运行 MySQL、不操作生产、不回退同工作区其他人的改动。

## 验收

- 复用 canonical guards；干净目录中没有旧 Console 输出仍能完整生成。
- 原 HEAD 全部 allOf 保留，包括 ConsoleCommandResult 的 READY/WAITING guard。
- 新知识 resolution/evidence 与 optional 父绑定保持 canonical parity。
- 连续两次生成字节相同；独立正/反安全组合与真实 schema payload 增量通过。
- 无需改库、不篡改审计、不扩大既有权限。root 独立 review 后统一提交。
