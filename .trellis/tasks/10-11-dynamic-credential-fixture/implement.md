# 实现与验证

新增 source-only AST provenance helper。接口、generic redaction、artifact/role 权限和
数据库契约不变。只对精确可定位的动态名字赋值插值匹配提供语法例外，强规则检查原文。
写入索引一次建立；同一局部 binding 的重复插值复用临时 ambiguity fact。

最小回归先运行：7 failed / 25 passed，失败对应真实动态负向测试输入及完整新增 hunk。
随后修复并运行 source/generic/Git 增量：233 passed；独立 reviewer 找到已知 mock patch
拼接 target 绕过，补红测、修复，专项51 passed，相关237 passed。末次性能缓存修改后的
相关组为 **237 passed in 26.89s**。不运行全量，不增加依赖。

```sh
PYTHONPATH=src <main-venv>/bin/python -m pytest -q \
  tests/context/test_dynamic_credential_source.py \
  tests/context/test_source_secret_detection.py \
  tests/context/test_generic_redaction_scope.py \
  tests/git/test_mutation_capture.py --tb=short
```

最后 alias 修复后 **54项专项、240项相关测试通过（26.03s）**；独立复核确认已知
mock/monkeypatch动态目标及alias全部拒绝，合法动态与明确无关对象setter仍可用，无剩余阻塞项。
Ruff format/check 与 MYPYPATH=src/PYTHONPATH=src strict mypy 3文件通过。真实Git
fixture验证 capture、wire roundtrip、verify，不改 index/源文件。

## 存量数据处置

原 K1 run8 `run_726f7c0c0ddb484f92c1a4de775a9b4d` 的真实 stop 是 local_execution_limit。
其 invocation outcome和receipt仍缺失；此次不改写为完成或补造报告。
只读使用新 detector完整 capture 30项（这包括完整mutation表示，非仅本轮新增路径），
并通过wire roundtrip和verify。2,440条inventory前后相同：
`a6618fd42c716889f1d9af784b135cd9f96a0dfedac45a45811572eb9bfc2ccd`。
补丁hash `c085ce5563e49e446c861eb4771cc3634af2f8ad0ebb27181175d9cbf80211f5`。
HEAD e4023c4、源码、index未修改；没有 store.put 或 SQL 写入。

两次只读探针曾在最终摘要输出时报 Python AttributeError（误用entries/diff_sha256），
其之前capture/wire/verify断言已通过；修正为files/sha256(patch)后的整条探针成功。
不把探针输出失败记录当作生产故障或新恢复依据。

部署后通过public PROPOSE准备完整原Task恢复，精确审批PAUSE再显式RESUME，不能直接
写库、改源码测试、退款或重建需求。回滚须保留新封存语法的reader兼容，不改记录字节。

## 已知边界

这是明确的静态语法规则，不能证明任意未知调用没有反射副作用。常见namespace/frame/
mock反射入口拒绝。无partial-hunk跨文件数据流证明；缺失证明保持保守。尚未部署。
