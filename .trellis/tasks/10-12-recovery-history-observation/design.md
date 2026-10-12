# Compact verified-prefix receipts 设计提案

本文件是待审查设计，不是已接受spec或已实现契约。先完成静态设计review，再写正确service
seam的红测；不得先添加缓存后仅在浅层helper上验证。

## 1. 接口与固定typed projection

建议新内部模块 `recovery/requirement_history_observer.py`。它不接受调用方decoder/validator，
不持有模型、数据库、写store或执行权限；只有生产composition和测试端口可构造。

```python
class VerifiedJointRecordFacts(DomainModel):
    codec_version: Literal["native-joint-prefix-v1"]
    delivery_id: DeliveryId
    sequence: int                         # >= 1
    checkpoint_sha256: Sha256
    previous_checkpoint_sha256: Sha256 | None
    team_id: TeamId
    team_manifest_sha256: Sha256
    project_id: ProjectId
    project_manifest_sha256: Sha256
    child_delivery_ids: tuple[DeliveryId, ...]  # 本条 children 的精确ID投影

@dataclass(frozen=True)
class VerifiedJointEdge:
    # 所有值只能由固定完整codec在校验成功后生成，不接受caller登记。
    payload_sha256: str
    predecessor_payload_sha256: str | None
    facts: VerifiedJointRecordFacts
    retained_bytes: int

@dataclass(frozen=True)
class NativeRequirementPrefix:
    current: JointCheckpoint | None
    records: tuple[VerifiedJointRecordFacts, ...]

def observe_native_requirement_prefix(
    root: Path, delivery_id: DeliveryId,
) -> NativeRequirementPrefix: ...
```

owner内部key还包含绝对root/path、固定model/codec和delivery+序号身份。不能只按checkpoint
摘要索引；不同Project、路径或codec不能共享receipt。`child_delivery_ids`保持完整，不给它
静默截断；非常大的合法投影无法注册时走完整fallback，仍返回准确结果。

receipt只记固定原始字节及精确前边校验，不保存完整JointCheckpoint图、完整rawbytes或已
批准/可执行结论。当前head从每轮fresh fullbytes独立完整解码/校验，并返回private deep copy。
不跨观察保留完整head模型；这比“缓存所有历史，只有head给调用方”有更清楚的内存界限。

## 2. 冷读与温读的完整前缀算法

每次observe都执行原有完整regular-file preflight和Journal读取/byte SHA；不把两次完整读
合并为一次。新模块必须复用现有安全path/file read端口，不能以resolve先吞掉symlink信息。

1. fresh枚举所有record名并排序；保留完整inventory和原来的first/sequence规则，不缓存glob。
   root、各ancestor和每个record的symlink/regular约束与完整字节读取均照常执行。
2. 每文件完整payload SHA与**本轮刚读取的**preceding payload SHA形成exact edge key。
3. **冷读/未命中**：固定 `JointCheckpoint.model_validate_json`、`validate_integrity`、文件名/
   delivery/sequence校验及原 `_validate_successor(previous, current)` 全部执行。成功之后才
   生成本条projection及edge receipt；失败不会登记negative、partial或更弱结果。
4. **温读命中**：只有path/codec/delivery/sequence/fullbytes/predecessor fullbytes均精确相同
   时，复用曾由完整codec完成的内在与successor校验；返回private projection copy。head仍
   完整解码/校验，从未返回旧的current对象。不能只比较mtime/size/semantic摘要。
5. 若前一条温读没有保留完整model而当前需要完整successor校验，重新完整读前条、比较与本轮
   已观察SHA、完整解码前条后调用原 `_validate_successor`。若重读时字节变化，本轮拒绝；
   不用compact投影模拟 `_validate_successor` 的全部复杂规则。
6. 本轮任何文件消失、错误名/身份、祖先重封、错误predecessor、symlink或混合prefix均拒绝。
   缺first/中间文件由原完整successor规则拒绝。新增tail全部读取并验证后返回新head。
7. 扫描必须完整结束后才返回prefix。既有source/nativefacts before/after再次observe的次数
   不变；本次有限inventory不成为下轮current事实。

如果祖先payload变化，即使其checkpoint语义摘要或长度/mtime不变，也不能使用旧edge。
变更record先逐出其receipt；下一边predecessor SHA不匹配，自然重新校验。后面的不变边在
前缀已重新完整验证后才允许复用相同bytes+predecessor的固定结果。缓存饱和仅增加完整decode，
不能增加新的record-size拒绝、丢弃foreign历史或略过successor。

## 3. 退休与parent的最小typed seam

现在 `RequirementRetirementStore.require_native_active()` 需要完整history，扫描历史所有
`parent.children` 的native ID，使用最新head校验退休hash/owner，再使用最新plan派生native IDs，
最后验证replacement。parent helper对全部需求调用current，检查owner及联合批准delegation。
这些判定必须复用原实现；不能在新observer复制一套略不同的授权逻辑。

建议增加内部可选能力：

```python
class NativeChildHistoryReader(RequirementCheckpointReader, Protocol):
    def native_child_history(
        self, delivery_id: str,
    ) -> tuple[VerifiedJointRecordFacts, ...]: ...
```

退休checker获得该能力时，对完整每条projection扫描 `child_delivery_ids`；否则继续使用原
`history() -> tuple[JointCheckpoint, ...]` 路径。最新head仍由 `current()` 得到完整私有
JointCheckpoint，用现有owner/hash/plan/replacement规则处理。测试必须证明两种端口对合法、
退休、replacement和全部失败矩阵的结果相等。compact类型应放在无循环的内部共享模块，
避免multi_directory下层依赖recovery composition；review可选择domain-level typed DTO所在位置。

`_NativeRequirementHistory` 对单次parent观察保持已有read-local `_currents` 行为；每个新的
initial/parent观察创建新adapter，重新full read/inventory。跨观察仅共享固定edge receipts。
`_parent` 的完整搜索、DerivedStageInputs、native ancestry、operator/rationale、歧义拒绝全部保留。

这个桥接需要 `multi_directory/retirement.py` 和 `recovery/native.py` 的极小内部改动，超出
root初始代码ownership。**本阶段只指出缺少的seam；必须先由root/reviewer决定范围。**
如果范围不能扩大，下一阶段只能完成observer/红测与安全局部接入，不能伪称已优化完整退休链。

## 4. 作用域、总预算与private copy

保持既有 `RecoveryRecordReads` owner-thread/owner-async-task身份约束与正常/异常close，增加
固定journal projection登记。共享owner下context、baseline-plan/start及journal receipts的
**总条数最多512、总记账字节最多32MiB**；不为每Project或每journal另开32MiB池。

receipt成本使用compact序列化+key+SHA/fixed metadata记账；既有record成本仍包括其raw+typed
serialized footprint。所有登记先检查共同额度。必要时budget预留/优先级另建任务，不在此
设计中引入动态调节、无上限model cache或跨request LRU。

512条上限足以覆盖当前259条Journal receipts，32MiB可容纳其compact metadata，但与既有
Context/baseline共用时也可能溢出。本任务验收不能假设生产全部命中；必须测混合命名空间的
配额与完整fallback。不要宣称这就是32MiB total Python heap/RSS硬上限：当前head、返回对象、
decoder暂存和调用栈中的既有NativeFacts不属于retained缓存，仍需独立观察峰值。

projection使用frozen typed字段，无mutable dict；仍返回private copies，不把owner中的对象
给调用方。完整head深拷贝，嵌套attempts改变不能污染后续current。跨thread/async拷贝ContextVar
不得继承父owner的复用或关闭权限。保留异常traceback也不能保留owner内旧receipt/model图。

scope复用固定在现有同步窗口：公开准备/approve、`NativeRecoveryEntry._execute` 的 admission
阶段、首次Coder `seed.authorize`的独立短scope。`entry.py:1085` 的
`finish_recovery_record_reads()` 保留，backend/model callback必须看到缓存已closed/空；
不能用decorator包整个真实provider回调。下一HTTP/operation重新cold。

## 5. 实际service seam与红测矩阵

复用 `tests/recovery/test_preparation_inspection_scope.py` 的真实Allocator→sealing→Builder→
NativeFacts结构与OfflineAuthority；结合 `test_capacity_parent_journal_scope.py` 的真实
Team/Project/retirement/replacement/journal/native checkpoint fixture。只替换SQL、claim、
no-start、Git capture/target事实为显式typed/计数fake，不mock新的observer或rawcodec。

首次allocate仍有32次source观察；整entry在分配前两次Builder另16次。对小fixture断言完整
每路径read/hash/inventory次数与旧链相同，全部freshfact/capture/authorization和两个fence
次数不变，祖先的fulltypeddecode次数仅按cold/miss计算，head每次完整解码不能被误算为失败。
先在当前代码跑红：32次观察仍重复解码同祖先；再实现固定receipt。无flaky时间阈值。

| 场景 | 必须验收 |
| --- | --- |
| 新分配，真实多条大字段Journal | source32/fence2不变，全读不变；祖先固定decode降至cold一次，head照常新鲜 |
| 整entry准备stub backend（不调模型） | total source48保留；provider回调看到空/closed owner |
| 首次seed admission | 原sealing/source与invocation一次性校验保留；provider前释放独立owner |
| 第二独立allocate/Operation | 冷读完整验证，无跨HTTP复用 |
| 相同length/mtime的历史篡改 | fullbytes SHA miss并拒绝；不发布dispatch |
| 历史祖先重新封hash，successor仍旧 | exact predecessor变化触发完整successor并拒绝 |
| first/中间记录缺失、错文件名/身份、symlink | 完整prefix拒绝，不能复用缓存head绕过 |
| warm后合法追加tail | 全部新增bytes/edge完整验证，新head立即可见 |
| 新退休/坏退休hash/replacement缺失 | fresh retirement读取拒绝或正确撤销，旧receipt不成为授权 |
| 多个parent匹配、foreign owner不符 | 原parent判定拒绝，不能提前返回首个match |
| 第二fence改变历史/claim/capture | 真实validate拒绝，dispatch未发布；不缓存currentfacts |
| 调用方改变完整head嵌套attempts | 下一full观察仍返回原字节事实 |
| 多root/Project、baseline+Context+journal混合 | 共同512条/32MiB上限；越界完整fallback，所有事实保持完整 |
| zero/one-byte预算、oversized projection | 完整decode/校验，不截断、不引入record-size新错误 |
| 正常、错误、保留exception traceback | owner条数/bytes归零，weakref释放可保留图，下一调用冷读 |
| copied thread/同thread asyncio子任务 | 不继承复用/close权，独立scope正确释放 |

仅运行新增observer/service红测、现有capacity/native retirement/parent、record-scope、固定
Journal和adapter admission相关增量测试。格式、类型、diff检查完成后独立review。

## 6. 风险、分期和回滚

最大风险是复制退休/parent权限判定、用compact字段不完整地重建successor规则、错误共享
freshfacts以及record quota把缓存变成新拒绝。这些由复用原policy方法、固定codec、exact edge、
真实第二fence负例、overflow fallback和pre-model生命周期测试防止。

本方案仅缩减祖先完整model解码；full reads/inventory、最新head解码、SQL baseline decode、
Context全目录验证、目标编译仍存在。因此验收是正确性/次数/内存retain合同，生产延迟必须
部署后实测，不能预先承诺精确耗时。热点依次独立处理，不在此任务顺便放宽权限或改UI。

实现不新增durable record，不改审批摘要和Schema，无数据迁移。旧Task/失败/现场保留。
仅在活动执行结束后按受控重启部署。回滚恢复普通完整历史读取组合，保持原需求可继续，
不得重建同名需求、清空journal、修改DB或代替角色verdict。
