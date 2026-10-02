# 还原路线（技术方案）

> 差分判定标准（改写 / 整段删+新写 / 压缩概述 + 采用口径）见 [restoration-targets.md](restoration-targets.md)「判定标准」。

## 1. 总体形状

```
backup/   (Steam 原版，只读，唯一基线)
   │   build（幂等；每次从 backup 起底）
resource/ (全部输入：译文表 / 承载图 / 改名表 / 插入计划 / 资源清单)
   ↓
asset/    (完整文件 = 构建产物；测试时直接覆盖游戏目录；可随时从 backup 重建)
   ↓   generate_payload
payload/  (增量，发布用) → 安装器
```

| 归档 | L1–L3（本体线） | L4（后日谈） |
|---|---|---|
| `Rio.arc` | 还原插入（A-1 补 5 个脚本 + 恢复 5 处跳转；A-2/A-3 就地插入）；补中文 `.lng`/`NameTable` 派生项 | `start.ws2` 就地改 `SetFlag 1000`＝1（解码偏移 5） |
| `zh-CN/Rio.arc` | 宿主 `.lng` 按新槽位序重建 + `NameTable` 合并 | 追加 4 个 `SL_*.lng`（构建时从 `resource/fan_cn/SL_*.json` 现做）＋ `NameTable.txt` 合并（同一次合并，见 §4.1） |
| `Script.arc` | 系统/引擎层，**不改动** | **改动**：`LegacyGame.lua` 两处（门控 `0x234b0`、常量 `openSceneSelect`→`openAfter` `0x2a18`）＋ `ArcFileName.lua` 注入 `flag 126` 路由分支 |
| `GRAPHIC.arc` | 缺失的原版图形；**33 张后日谈分层立绘 `.pna` 判给本工序**（引用面全在主线脚本），产物必须含这 33 名 | **不写盘**；只按名端到端验收那 33 名在位（§4.1） |
| `SE.arc` | 补入缺失项 | 追加 3 个 `PSE` 独有 SE（`T_se91`／`pw129_4`／`se43b`） |
| `VOICE.arc` | 补入范围内缺失的原版语音 | 不涉及 |
| `CHIP2/3/5/6.arc` | 补入范围内缺失的立绘/CG；**同名冲突改名隔离** | 不涉及 |
| `CHIP4.arc` | 补入缺失项 | 不涉及 |
| `PVOICE.arc` / `PCHIP.arc` | — | **新增裸归档**（原版整档复制，放游戏根目录，靠 `flag 126` 路由可达） |
| 裸 `RIO/` | — | **新增 4 个 `SL_*.ws2`**（原版→Steam 编码后交付，与原版スウィートラブパッチ同形） |
| `BGM.arc` / `SysVoice.arc` | **不改动** | **不改动**（`PBGM` 分支不注入） |
| `SysGraphic.arc` / `Effect.arc` | **不改动** | **不改动** |

## 2. 硬纪律

1. **基线只有一个 = `backup/`**。`asset/` 任何时候都能从 `backup/` + `resource/` 重建。
   验收含**可复现性**：从 `backup/` 起底跑两次，产出归档**逐字节一致**。
2. **零破坏性**：不替换 Steam 原有资源；同名冲突一律**改名隔离**（命名规则见 [restoration-targets.md](restoration-targets.md)「贯穿各层的约束」）。
3. **就地插入，不新增脚本、不新增跳转**。
   - **A-1 是唯一例外**：那 5 个脚本**原版就有**，还原 = ①把脚本补回 `Rio.arc` ②把前序脚本被改写的 5 处尾跳**改回原版目标**（`ASA_001`→`ASA_002`、`ASA_003`→`ASA_004`、`YOR_002`→`YOR_003`、`YOR_004`→`YOR_005`、`YOR_006`→`YOR_007`）。这是**恢复原版跳转**，不是新增跳转。
4. **同一归档只允许一趟写盘**。两线都会写的归档 = `Rio.arc`、`zh-CN/Rio.arc`、`SE.arc`（见 §1 表）。各自从 `backup/` 起底重建再整档覆盖 ⇒ **后写入的一方顶掉先写入的一方的全部改动**。合并方式二选一：① L4 的改动项并入主线写盘器的**同一趟**（`asset/` 单棵输出树）；② L4 以主线 `asset/` 为**输入**做增量（此时 L4 的可复现基线＝主线产物 + `resource/`，不再是 `backup/`）。`Script.arc` 本体线不改动 ⇒ 直接取 L4 版；`GRAPHIC.arc` L4 不写盘 ⇒ 直接取主线版。工序归属与判据见 [afterstory-mechanics.md](afterstory-mechanics.md) §10。

## 3. 本项目的结构性优势

| 项 | 本项目 | 依据 |
|---|---|---|
| 原版脚本格式 | **与 Steam 同为 WS2**（rotate-6 同码）⇒ 解码/对位直接复用；**执行编码须经 G3 转换器转为 Steam 形**（两版 256 项格式表实质差 9 条，全量差分确认完备，见 `convert_sl_ws2.CONV`） | 两版 `Rio.arc` 的 `.ws2` 都能直接解码；表差分 2026-10-02 实测 |
| 原版资源可用性 | **可直接复用**（两版**同引擎、资源互通**） | 已确认 |
| 还原内容的中文 | **民汉语料已全量覆盖原版**：`resource/fan_cn/*.json`（按**原版 idx** 索引，54,253 槽）⇒ **还原插入的原版行直接有现成中文**，无需翻译 | 文本层已通过验收 |

## 4. 流水线

| 步 | 脚本 | 作用 |
|---|---|---|
| 1 | `script/build_carrier_map.py` | **承载图**：原版行 `r` → Steam 槽位 `k`；出逐脚本 blocks → `resource/carrier_map.json` |
| 2 | `script/build_rename_map.py` | 同名冲突**改名表**（原版名 → 补丁名）；规则解不掉的**单列，不许静默跳过** → `resource/rename_map.json` |
| 3 | `script/build_restore_plan.py` | **插入计划**：宿主脚本 / 插入点 / 源行区间 / 随行演出 / 取哪条中文 → `resource/restore_plan.json` |
| 4 | `script/build_patch.py` | **从 `backup/` 起底**：逐脚本写盘（插入 / 删格 / 名字框同步 / **跳转回写**）+ 补资源 → `asset/` |
| 5 | `script/generate_payload.py` | `asset/` vs `backup/` → `payload/` + `METADATA.json` + **回读校验** |
| 6 | `script/final_verification.py` | 全量验收 |

**闸的次序固定**：**只看表**（表自洽：格数自洽 / 覆盖无空档 / 行序单调）→ **写盘** → **表↔产物** → **全量验收**。

**写盘器硬要求**：

- **必须回写文件内跳转**：插入会平移其后所有字节，而 `06 <u32>` 等记的是**文件内绝对偏移**，不回写会让选项/双出口**跳错**。
- **`.lng` 按播放序对位，且一律在写盘时现做**：宿主就地插入会使其后所有台词槽位平移，`zh-CN/Rio.arc` 的宿主 `.lng` 须按**新槽位序**重排——保留格取官方 `.lng` 原条目、插入格取民汉条目（`resource/fan_cn/`，按**原版 idx**）。U-10 的 20 个条目数与台词数不齐的成员必须先对账；**预检**：无官方 `.lng` 的共享脚本不得进入宿主名单。
- **派生形态不留档**：`.lng`（含 A-1 那 5 个整脚本的 `.lng`，按原版 idx 1:1 现做）与合并后的 `NameTable.txt` 都是**装载形态**，写盘时从主产物现做并封进归档；`resource/` 只存主产物与输入，存副本会与主产物分波重建而静默落后。名牌表合并走唯一出口 `script/build_nametable.py`（官方 94 键保序在前 + `resource/fan_cn/NameTable.json` 的日文键追加，读取时把组合名中点 `·`→`・` 归一）。
- **指令排布照抄 Steam**：相邻 `15`（设名）**不折叠**；`drop` 删**整格**（`14` + 设名 `15` + 清框 `15`），带「不改动任何存活格名字框」的守卫。
- **名字框是"继承"语义**：插入段发完必须**恢复现场**（重发进入时那条名字框），否则紧随的原始格会张冠李戴。
- **逐槽核"该槽有没有处置"，漏一格即中止**（不静默产出空条目）。

### 4.1 后日谈（L4）在施工层里的位置

L4 的改动**全部属步骤 4（写盘）**；步骤 3 的「插入计划」对其不适用 —— 后日谈不往宿主脚本里插行，而是**整脚本回填**（4 个 `SL_*.ws2`）＋**门控与路由**（Lua 与 `start.ws2`）。机制与偏移依据见 [afterstory-mechanics.md](afterstory-mechanics.md) §9，工序归属判据见其 §10。

| 项 | 落点 | 脚本 | 输入 | 构建期断言 |
|---|---|---|---|---|
| G1／G2 | `Script.arc` → `LegacyGame.lua` | `script/build_l4.py` | `backup/` 成员字节 | 目标字节序列（`49 c0 c6 8b`、`\x04<len=16>"openSceneSelect"\0`）逐一命中才改，全库唯一 |
| G3 | 裸 `RIO/SL_*.ws2` | `script/convert_sl_ws2.py` | 原版裸 `RIO/` | Steam 表回读：指令数／操作码／操作数／尾部一致 ＋ 跳转目标落位 |
| G4 | `Rio.arc` → `start.ws2` | `script/build_l4.py` | `backup/Rio.arc` | 解码后偏移 5 的 `00`→`01`；其余成员逐字节不变 |
| G5 | `zh-CN/Rio.arc` → 4 个 `SL_*.lng` | `script/build_l4.py` | `resource/fan_cn/SL_*.json`（875／851／714／788 槽） | `encode_lng`→`parse_lng` 逐槽回读 ＋ 归档回读等于内存 blob |
| G6 | `Script.arc` → `ArcFileName.lua` | `script/build_l4.py` | `backup/` 成员字节 | 常量追加在末尾 ⇒ 既有索引不变；插入块内跳转全为块内相对；graphics +66／sound +34 条数核对 |
| G7 | `PVOICE.arc`／`PCHIP.arc`（裸归档） | `script/build_l4.py` | 原版根目录裸归档 | 整档复制，成员数与字节数核对 |
| G8 | `SE.arc` +3 | `script/build_l4.py` | 原版 `PSE.arc` | 逐名断言「原版有、Steam 无」 |
| G9 | `GRAPHIC.arc`（**L4 不写盘**） | `script/build_l4.py --verify <产物目录或 GRAPHIC.arc>` | 产物 `GRAPHIC.arc` ＋ 原版／`backup/` 基线 | 逐名断言 33 名在位 ＋ 名单未漂移（原版有、Steam 基线无） |
| G10 | `zh-CN/Rio.arc` → `NameTable.txt` | `script/build_nametable.py` | `backup/zh-CN/Rio.arc` 官方表 + `resource/fan_cn/NameTable.json` | 官方条目保序且值不被改写；`SL_*` 用到的 8 个日文名牌键逐一在表 |

**现状与接口**：`script/build_l4.py` 与 `script/convert_sl_ws2.py` 输出到同一棵独立测试树 `tmp/_l4/asset/`（`RIO/` 放 G3 的裸脚本），从 `backup/` 起底、可复现（跑两次逐字节一致）。原版发行目录**不进版本库**，两个构建器都按 `--orig-dir` 或环境变量 `IFMH_ORIG_DIR` 取用（口径见 [restoration-targets.md](restoration-targets.md)「素材来源」），未提供即拒绝运行。它与主线**重叠 3 个归档**（§2 硬纪律 4），故并入主线时二选一：L4 改动项进主线同一趟，或 L4 改以主线 `asset/` 为输入。

**判给本体线的前置项**（判据＝引用面，逐项实测见 [afterstory-mechanics.md](afterstory-mechanics.md) §10.1）：33 张 `.pna`（G9，全部被原版主线脚本引用 ⇒ L4 不搬运）、`se43b`（G8 的三分之一）、日文名牌键全量合并（G10 的条目来源 `resource/fan_cn/NameTable.json`）、原版→Steam 的 WS2 编码转换（G3 的工序）。L4 的净自有交付＝门控与路由（G1／G2／G4／G6）＋后日谈独有资源（G7、`T_se91`、`pw129_4`）＋ FD 文本层（G5）。

**后果**：L4 的输出树不含 `GRAPHIC.arc`，因此它**不是**一份可完整实机验证的后日谈 —— 立绘缺失会让 `st01` 等槽报 `サブプレイヤーが存在しません`。后日谈的实机与验收一律跑在本线产物上（`python script/build_l4.py --verify <产物目录>`）。

## 5. 验收

1. **归档完整性**（`tool/arcbuild.verify()`，含无 null padding）
2. **调用链完整性**（跳转目标全部可达；A-1 的 5 处跳转已恢复）
3. **成就触发点完整性**：Steam 的 **922 处 / 51 脚本**调用 + **29 处 `0xF0`** 逐点核对，**指令与成就 id 均不变**，一处不少、不新增、不重算
4. **资源配对正确性**（插入段引用的原版名 → 改名表 → 产物成员，逐个可解析）
5. **零破坏性核实**：`backup/` 未被写入；Steam 原有成员**未被替换**
6. **可复现性**：从 `backup/` 起底跑两次，归档**逐字节一致**
7. **实机测试**（关键场景：A-1 的 5 个整脚本入口、A-2 的插入点前后；后日谈入口 = `mainmenu` 调 `openAfter` → `start.ws2` 置 `flag 1000` → `flag 126` 路由取 `PCHIP`/`PVOICE` 资源）
8. **交付项完整性**：构建期名单逐名断言，不以覆盖率代替 —— L4 自有交付为 `SE.arc` 含 3 个 SE、`zh-CN/Rio.arc` 含 4 个 `SL_*.lng`（875／851／714／788 槽）且 `NameTable.txt` 含 `SL_*` 用到的 8 个日文名牌键、裸 `RIO/` 含 4 个转码后的 `SL_*.ws2`；**端到端验收**为产物 `GRAPHIC.arc` 含 33 张后日谈 `.pna`（`python script/build_l4.py --verify <产物目录>`，L4 不搬运）

## 6. 已确认的技术结论

| # | 结论 |
|---|---|
| V-1 | **两版游戏使用相同引擎，资源互通** ⇒ 原版资源可直接复用，无需重编码 |
| V-2 | 同名冲突命名：统一用**单开编号段**（`9X` = L1–L3、`8X` = L4，从后往前，所有资源类一律适用）；被删除、Steam 缺失的资源**直接继承原版编号**。详见 [resource-naming.md](resource-naming.md) |
| V-3 | `LAYER_ORDER` 重排语义两版相同，不构成障碍 |
| V-4 | 成就由开发者与 Steam 共同管理，本补丁**只保留触发点**：指令与成就 id 原样保留，**不新增**任何触发指令；被删 5 脚本内的 332 处 CG 位点**不补钩子**（Steam 本身未在此设成就） |

## 7. 待办

- **V-5 插入点与形态逐段定案**：`resource/carrier_map.json` 里标 `ambiguous` 的中部缺口（原版行 4,769 / Steam 格 1,115）需逐段读原文定形态。
  **判据**：头部缺口机器可定（按尾对齐，多出的原版行在头部 ⇒ 删除）、尾部缺口按头对齐；**中部缺口两侧条数不等时机器不猜**。
  - 已定案的示例：`YOR_004` seg0（原版 0–84）⇒ 插入点 = Steam **第 0 槽之前**；`AGE_006` 原版 284–304 ⇒ **改写 + 整段删 + 压缩概述混合**，插入点在 Steam 槽 278 与 279 之间。
- **V-6 B 清单重判**：早期按「内容存在性探针」分出的 C 型「新增⇒保留」与小规模 D 型，须按 [restoration-targets.md](restoration-targets.md)「判定标准」重判。
- **转换器缺口已补齐**：`CONV` 已补 `0x1c`(end1)/`0x35`(end1)/`0x56`(end4)，依据 = 两版 256 项格式表**全量差分**（实质内容差恰 9 条，无遗漏；SL 输出 md5 复验逐字节不变）。Steam 表线性解析失步的 8 个成员（`CG_PAGE09-12`/`CO1_018`/`CO2_005`/`HUT_005`/`Pan.dat`）**均不在本体写盘目标与 orig 提取源名单内**（CG_PAGE 延后、CO1_018/CO2_005 无台账写项、HUT_005 台账全 keep、Pan.dat 非 WS2）；实际需解析的 47 个 orig 源中仅 `HUT_005` 原版失败且无需提取。`tool/ws2dis.disassemble()` 的 `ok` 标志只校验尾部长度、查不出流中部失步——管线各闸不把它当可解析凭证，一律以「Steam 表回读 + 指令数/操作码清单/跳转落位」为准。

## 8. 与既有产物的关系

- **文本层**（`resource/fan_cn/*.json` + `NameTable.json`）**就是** `resource/` 的输入表之一，直接沿用；`.lng` 与合并后的 `NameTable.txt` 只是装载形态，按 §4「派生形态不留档」在写盘时现做。
- `tool/` 已有 `arcbuild.py`（归档读写 + `verify()`）/ `ws2.py` / `ws2dis.py` + `ws2fmt.txt` / `scriptext.py` / `lng.py` / `pna.py` / `fancn.py` / `textfix.py` / `v5lib.py`，与参照项目同源，可直接扩展。
- **施工层已在链**：步骤 1／2 的 `script/build_carrier_map.py`、`script/build_rename_map.py`；L4 侧的 `script/build_l4.py`（写盘 G1／G2／G4～G8／G10，G9 只做端到端验收）、`script/convert_sl_ws2.py`（G3）、`script/build_nametable.py`（G10 唯一合并出口）。L4 现输出到独立测试树 `tmp/_l4/asset/`，并入主线按 §2 硬纪律 4 二选一。
- **尚缺**：`script/build_restore_plan.py`、`script/build_patch.py`、`script/generate_payload.py`、`script/final_verification.py`（§4 步骤 3／4／5／6），`tool/writer.py`（结构写盘器）。反汇编已由 `tool/ws2dis.py` 承担（操作数格式表从引擎 `off_553EC0` 导出，对本作权威）。
