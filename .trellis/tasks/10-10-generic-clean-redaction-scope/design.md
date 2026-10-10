# 同步纯检测缓存设计

复用已有ContextVar和source_inspection_scope生命周期，增加typed generic key；source/patch
维持原3槽key。generic第2槽引用实际不可变(kind, compiled pattern)tuple（包含顺序），第3槽
保留完整正文比较。Python编译pattern按定义及flags相等，语义相同的新对象可复用；kind/
定义/flags/顺序变化则不相等。只存empty occurrence tuple；命中时构造新的RedactedText，命中输入和
RedactedText不入generic缓存。扫描前捕获本次rules tuple，lookup与执行绑定同一组规则。

三种mode共用512项/16 MiB原上限，ledger记录每个实际key的UTF-8正文及path大小。规则只是
常量引用，无regex字符串复制；对象开销仍由条目上限限定，不把payload上限说成堆内存上限。
超字符下界先拒绝，UnicodeEncodeError不引入原检测没有的拒绝。

source/patch的内部generic调用使用同步嵌套depth guard，始终原regex扫描，不占父事实预算。
guard只包cache-miss scanner，finally成对恢复；cache-hit不进入guard。独立generic调用可以
命中/缓存，但为可逐出的临时优化。新source/patch需要空间时，先完整计量目标且确认逐出所有
generic后能够容纳，再按已有顺序只逐出必要generic条目；不动任何source/patch事实。若目标
不能容纳则不逐出。原terminal的7110B精确body+path预算契约因而继续成立。

同一scope内源文件、目录、SQL、捕获、停止事实、双读与exact审批保持原次数；仅省略相同
rules+正文的已确认无命中通用regex扫描。不新增配置、Schema或持久化缓存，不跨异步/模型执行。

存量数据无需迁移，现有需求与Task不写入；运行服务尚未部署本改动。回滚本次generic分支、
key类型、ledger/guard即可恢复原扫描成本，不能改变历史hash或审批。
