# 还原路线（技术方案）

> 差分判定标准（改写 / 整段删+新写 / 压缩概述 + 采用口径）见 [restoration-targets.md](restoration-targets.md)「判定标准」。

## 1. 总体形状

```
backup/   (Steam 原版，只读，唯一基线)
   │   build（幂等；每次从 backup 起底）
resource/ (全部输入：译文表 / 承载图 / 覆盖判定表 / 插入计划 / 资源清单)
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
| `GRAPHIC.arc` | 缺失的原版图形；同名冲突按**同一判据**分类处置（`.pna` 也走覆盖，但**必须先确认两侧图层数与层序等价**，不等价者判为**不动**并单独人工裁定，见 [resource-naming.md](resource-naming.md) §3）；**33 张后日谈分层立绘 `.pna` 判给本工序**（引用面全在主线脚本），产物必须含这 33 名 | **不写盘**；只按名端到端验收那 33 名在位（§4.1） |
| `SE.arc` | 补入缺失项 | 追加 3 个 `PSE` 独有 SE（`T_se91`／`pw129_4`／`se43b`） |
| `VOICE.arc` | 补入范围内缺失的原版语音 | 不涉及 |
| `CHIP2/3/5/6.arc` | 补入范围内缺失的立绘/CG；同名冲突**一律整名覆盖**（同名成员换成原版字节，不保留 Steam 画面）、噪声不动；顶包（Steam 那张实为原版另一帧的副本）**也不隔离改名**，只把**还原后仍保留的那一个显示调用点**改写成那一帧的原版名（判据见 [resource-naming.md](resource-naming.md) §1–§3） | 不涉及 |
| `CHIP4.arc` | 补入缺失项 | 不涉及 |
| `PVOICE.arc` / `PCHIP.arc` | — | **新增裸归档**（原版整档复制，放游戏根目录，靠 `flag 126` 路由可达） |
| 裸 `RIO/` | — | **新增 4 个 `SL_*.ws2`**（原版→Steam 编码后交付，与原版スウィートラブパッチ同形） |
| `BGM.arc` / `SysVoice.arc` | **不改动** | **不改动**（`PBGM` 分支不注入） |
| `SysGraphic.arc` / `Effect.arc` | **不改动** | **不改动** |

**交付面**：`asset/` 只写相对 `backup/` **有差异**的归档；无差异者（`BGM.arc`／`Chip1.arc`／`SysVoice.arc`／`SysGraphic.arc`／`Effect.arc`）**不进 `asset/`**，安装期由玩家原档直接提供。`Chip1.arc` 落进无差异一类，是因为它的图形需求在 Steam 侧**已有同名同内容成员**（成员名仅大小写不同），补入只会造出重名成员。
**「有差异」的口径含覆盖**：整名覆盖**不新增成员**，只换同名成员的内容 ⇒ 覆盖名单命中某归档即该归档**有差异**，不得以「无净增成员」判成无差异而跳过写盘（见 §4 写盘器硬要求）。

## 2. 硬纪律

1. **基线只有一个 = `backup/`**。`asset/` 任何时候都能从 `backup/` + `resource/` 重建。
   验收含**可复现性**：从 `backup/` 起底跑两次，产出归档**逐字节一致**。
2. **改动面收敛**：只改写**还原范围内**的内容——范围外的 Steam 资源一律原样。同名冲突**一律整名覆盖**（成员换成原版字节，Steam 版画面不保留）、噪声不动，**没有隔离改名这条路线**；顶包只在**还原后仍保留的 Steam 格**上改写那一个显示调用点（判据见 [resource-naming.md](resource-naming.md) §1–§3）。覆盖的合法性**只来自入库判定表的 `overwrite` 子集**：子集内每一名的替换可追溯到判定证据，**子集外的 Steam 成员不得被替换**。处置细则见 [restoration-targets.md](restoration-targets.md)「贯穿各层的约束」。
3. **就地插入，不新增脚本、不新增跳转**。
   - **A-1 是唯一例外**：那 5 个脚本**原版就有**，还原 = ①把脚本补回 `Rio.arc` ②把前序脚本被改写的 5 处尾跳**改回原版目标**（`ASA_001`→`ASA_002`、`ASA_003`→`ASA_004`、`YOR_002`→`YOR_003`、`YOR_004`→`YOR_005`、`YOR_006`→`YOR_007`）。这是**恢复原版跳转**，不是新增跳转。
4. **同一归档只允许一趟写盘**。两线都会写的归档 = `Rio.arc`、`zh-CN/Rio.arc`、`SE.arc`（见 §1 表）。各自从 `backup/` 起底重建再整档覆盖 ⇒ **后写入的一方顶掉先写入的一方的全部改动**。合并方式二选一：① L4 的改动项并入主线写盘器的**同一趟**（`asset/` 单棵输出树）；② L4 以主线 `asset/` 为**输入**做增量（此时 L4 的可复现基线＝主线产物 + `resource/`，不再是 `backup/`）。`Script.arc` 本体线不改动 ⇒ 直接取 L4 版；`GRAPHIC.arc` L4 不写盘 ⇒ 直接取主线版。工序归属与判据见 [afterstory-mechanics.md](afterstory-mechanics.md) §10。

### 2.1 调用链组织（段级就地插入）

**跳转指令格式**：脚本尾跳为 `\x02 <目标脚本名，ASCII 大写，无扩展名> \x00 <4 字节数值>`，目标名前后有非文本控制字节 ⇒ 提取/改写引用一律用精确字节模式匹配（见 [file-formats.md](file-formats.md)）。

**两类删减模式**（Steam 改写调用链的两种方式）：

- **整段跳过（A-1）**：脚本文件在 Steam 版完全消失，前序脚本的尾跳被直接改写指向更后面的脚本（例 `ASA_001`→`ASA_003`，跳过 `ASA_002`）。
- **脚本内原地删减（A-2）**：脚本文件仍存在、首尾跳转目标不变，中段对白被删（例 `AGE_010`）。仅比对「文件是否存在」发现不了，须比对同名脚本解码长度（差异显著者逐一核实）。

**还原方式＝段级就地插入**（不做整脚本替换）：

```
宿主 = [Steam 原生前段] + [原版插入段] + [Steam 原档出口尾段]
```

整脚本替换会抹掉 Steam 在该脚本内的新写内容、丢掉宿主承担的演出、造成顺序倒置与局部重复；段级插入只在被删区间原位补回原版内容，保留 Steam 原档结构与出口。插入单位按区段类型：`B 型（纯删除）` 原位插入原版段；`D 型（删除+新写）` 保留 Steam 新写（符合语境者）＋就地翻译，另在其间插入原版被删段。

**插入时必须逐处保留的 Steam 结构注入**（不得因插入而丢失）：

| 注入项 | 说明 |
|---|---|
| `\x04 CG_ACHIEVEMENT\x00` 成就触发点 | 原样保留指令与成就 id（基线 922 处 / 51 脚本）；H 区间内 CG 显示连同钩子被 Steam 一起删，还原时**不补**。契约见 [engine-mechanics.md](engine-mechanics.md) §成就触发点契约 |
| `LAYER_ORDER` 相关注入 | Steam 侧对 `LAYER_ORDER` 的形式改动与头部 `\x04 LAYER_ORDER\x00` 调用（见 [engine-mechanics.md](engine-mechanics.md)） |
| 其它未建模注入（`\xfb`／`timer01` 等） | 逐脚本核实后再动 |

**资源必须成对**：原版插入段引用的立绘/CG 须为**原版资源**，不可复用 Steam 同名资源（`layer_id` 是绑 PNA 记录数的位置量，混用会越界崩溃，见 [engine-mechanics.md](engine-mechanics.md)）。

**副作用**：插入会平移其后所有字节、改变脚本的 `0x14`/`0x0f` 槽位序 ⇒ ① 该脚本的 `.lng` 必须整体重建（lng 按播放序对位）；② 文件内绝对偏移跳转必须回写（见 §4「写盘器硬要求」）。

## 3. 本项目的结构性优势

| 项 | 本项目 | 依据 |
|---|---|---|
| 原版脚本格式 | **与 Steam 同为 WS2**（rotate-6 同码）⇒ 解码/对位直接复用；**执行编码须经 G3 转换器转为 Steam 形**（两版 256 项格式表实质差 9 条，全量差分确认完备，见 `convert_sl_ws2.CONV`） | 两版 `Rio.arc` 的 `.ws2` 都能直接解码；表差分 2026-10-02 实测 |
| 原版资源可用性 | **可直接复用**（两版**同引擎、资源互通**） | 已确认 |
| 还原内容的中文 | **民汉语料已全量覆盖原版**：`resource/fan_cn/*.json`（按**原版 idx** 索引，54,253 槽）⇒ **还原插入的原版行直接有现成中文**，无需翻译 | 文本层已通过验收 |

## 4. 流水线

| 步 | 脚本 | 作用 |
|---|---|---|
| 1 | `script/build/build_carrier_map.py` | **承载图**：原版行 `r` → Steam 槽位 `k`；出逐脚本 blocks → `resource/carrier_map.json`。1:1 块**另过内容面核对**——逐位比两侧**语音号归属**，两侧都有且不同 ⇒ 记入该块 `content_suspect`（`form` 标「内容存疑」）⇒ 该块**进入判读面**（`tool/v5lib.py::blocks()` 收它），计划器对「被直接承载的存疑对」**中止写盘**（见 [lessons-learned.md](lessons-learned.md) §14／§16） |
| 2 | `script/build/build_rename_map.py` | 号段编号的候选表。**同名冲突一律不进本表**（改名路线已取消 ⇒ 覆盖不改名，插入段照抄原版脚本里的名字即为正确）；`RENAME_ROUTE_RETIRED` 开关置位 ⇒ `voice`／`sprite`／`mos`／`est` **恒为空**，产物只留诊断清单（冲突面与引用面读数）→ `resource/rename_map.json`。消费端的取名映射（`plan.names`）同步停用、恒为空 |
| 2b | 图像冲突**判定表** | 两侧同名、**内容哈希不同**的图像成员逐个走「哈希筛 → 逐像素比对 → 全库最近邻 → 放大裁切匹配 → 顶包确认 + 存活格核对」（证据复算＝一次性比对脚本，落在 `tmp/`、**不入库、不作工序输入**，只读，逐名出证据与机械动作；**候选只按内容哈希筛，禁止按体积或尺寸筛**）＋人工看图定案，出 `class` ∈ `censor`／`reuse`／`noise` 与 `action` ∈ `overwrite`（非噪声者，**唯一覆盖动作**）／`keep`（噪声），含 `B`/`S` 同帧成组与 `.MOS` 伴生 → **`resource/censor_map.json`（已入库，`--emit-map` 写出、人工定案按名保留）**。`class=reuse` 不改变动作（仍覆盖），其下游动作是**在还原后仍保留的 Steam 格上改写那一个显示调用点**、登记在判读台账。判据见 [resource-naming.md](resource-naming.md) §1–§3；下游 3／4／5 步按本表的两个子集处置 |
| 2c | 语音冲突**判定表** | 两侧 `VOICE.arc` 同名、**SHA256 不同**的 `.OGG` 成员逐个解码（8 kHz 单声道 PCM）→ 5 ms 包络粗对齐 + 1 采样精修求原始 PCM 相关，出 `class` ∈ `noise`（仅容器差：相关 ≥0.98 **且** 时长差 ≤0.15 s）／`recode`（同录音被重编码/剪辑：相关 ≥0.5）／`rerecord`（换录音：相关 <0.5）与 `action` ∈ `overwrite`（非噪声者）／`keep`（噪声）→ **`resource/voice_conflict_map.json`**。生产者 `script/build/build_voice_conflict_map.py`（`--orig-dir`／`IFMH_ORIG_DIR`；ffmpeg 缺失时退化容器级判据）。判据见 [resource-naming.md](resource-naming.md) §3；下游 3／4／5 步按本表的两个子集处置 |
| 3 | `script/build/build_restore_plan.py` | **插入计划**：宿主脚本 / 插入点 / 源行区间 / 随行演出 / 取哪条中文 → `resource/restore_plan.json`。资源分派＝ **`copy`／`overwrite`／`have`**（`overwrite` 两路来源：图像取判定表 `censor_map.json` 的 `action=overwrite` 子集、语音取判定表 `voice_conflict_map.json` 的 `action=overwrite` 子集，两表都**逐名**入表、**不以被引用为门槛**；闸＝语音覆盖名单数须等于判定表 overwrite 数；**`rename` 分类已停用**）。顶包另出 `reuse_rewrites`（按 `surviving_sites` 的 `rewrite` 点） |
| 4 | `script/build/build_patch.py` | **从 `backup/` 起底**：逐脚本写盘（插入 / 删格 / 名字框同步 / **跳转回写**）+ 补资源 + **按覆盖名单整名替换同名成员** + **按调用点改写顶包显示名**，**只写有差异的归档** → `asset/` |
| 5 | `script/generate_payload.py` | 按 `asset/` 实际产物分三形态 → `payload/` + `METADATA.json` + **回读校验**（重放安装流程，须与 `asset/` 逐字节一致）：`copy` = 整档覆盖（`OVERWRITE` 名单里体量小的归档 + `backup` 无此档的新档，补丁档与交付路径同名）；`merge` = 资源级合并（其余归档出 `<名>_patch.arc` + 按 asset 序的成员表）；`loose` = 裸文件（`RIO/`）。`merge` 的成员类型已有 `added`／`modified`／`keep`／`deleted`，其中 **`modified`＝同名成员换内容**（按内容哈希判），安装期对 `added`／`modified` 一律取补丁字节 ⇒ 交付与安装层**无需新增类型**，覆盖能否落地只取决于第 4 步是否把覆盖成员写进 `asset/` |
| 6 | `script/final_verification.py` | 全量验收 |
| 6b | `script/verify_sync.py` | **文本-语音-CG 三元组一致性**（只读，两路对账）：**路 B** 在产物 `Rio.arc`（含 `zh-CN/` 叠加层）与资源归档上逐槽实测 (文本, 语音, 画面)，与 `resource/restore_plan.json` 声明的来源比对（保留格＝Steam 自己、插入格＝原版行），并把「画面／立绘／BGM 与期望不符」的读数**逐条归因**到删格残留或改写点（未归因＝0 才算收敛）；**路 A** 在承载图 1:1 块上核两侧语音号归属与文本形状，命中 `carried-1to1` 即判**还原缺口**并输出两侧原文供目视核对；**路 D** 逐名回读覆盖成员字节＝原版、顶包调点改写到位。HARD 级发现 ⇒ 非零退出 |
| 7 | `script/pack.sh` | **发布链**：PyInstaller onefile 把 `tool/install.py` + `payload/` + `VERSION` + `resource/icon.ico` 打成 `releases/` 单文件安装器（`releases/` 不进版本库）。安装期由 `tool/install.py` 按 `METADATA.json` 逐条交付（合并／整档覆盖／裸文件），交付后逐条校验哈希 |

**闸的次序固定**：**只看表**（表自洽：格数自洽 / 覆盖无空档 / 行序单调）→ **写盘** → **表↔产物** → **全量验收**。

**写盘器硬要求**：

- **必须回写文件内跳转**：插入会平移其后所有字节，而 `06 <u32>` 等记的是**文件内绝对偏移**，不回写会让选项/双出口**跳错**。
- **`.lng` 按播放序对位，且一律在写盘时现做**：宿主就地插入会使其后所有台词槽位平移，`zh-CN/Rio.arc` 的宿主 `.lng` 须按**新槽位序**重排——保留格取官方 `.lng` 原条目、插入格取民汉条目（`resource/fan_cn/`，按**原版 idx**）。U-10 的 20 个条目数与台词数不齐的成员必须先对账；**预检**：无官方 `.lng` 的共享脚本不得进入宿主名单。
- **派生形态不留档**：`.lng`（含 A-1 那 5 个整脚本的 `.lng`，按原版 idx 1:1 现做）与合并后的 `NameTable.txt` 都是**装载形态**，写盘时从主产物现做并封进归档；`resource/` 只存主产物与输入，存副本会与主产物分波重建而静默落后。名牌表合并走唯一出口 `script/build/build_nametable.py`（官方 94 键保序在前 + `resource/fan_cn/NameTable.json` 的日文键追加，读取时把组合名中点 `·`→`・` 归一）。
- **指令排布照抄 Steam**：相邻 `15`（设名）**不折叠**；`drop` 删**整格**（`14` + 设名 `15` + 清框 `15`），带「不改动任何存活格名字框」的守卫。
- **名字框是"继承"语义**：插入段发完必须**恢复现场**（重发进入时那条名字框），否则紧随的原始格会张冠李戴。
- **逐槽核"该槽有没有处置"，漏一格即中止**（不静默产出空条目）。
- **补资源只补 Steam 缺的成员，同名成员只按覆盖子集换**：需求成员名（忽略大小写）已在 Steam 归档内 ⇒ 默认**跳过**（不追加仅大小写不同的重名成员）；**唯一例外**＝入库判定表的 `action=overwrite` 子集（图像 `resource/censor_map.json`／语音 `resource/voice_conflict_map.json`）⇒ **整名替换为原版字节**，成员名与表位置不变。**子集外**的 Steam 成员一律不得改写；改名表**不得含判定表内任何成员的原名**（改名路线已取消，出现即中止并回到判据重定案）；`class=reuse` 的成员必须有**存活格核对结论**，缺结论即中止。覆盖子集必须**逐名对齐**实际替换次数（名单数 ≠ 替换数即中止，不得以"已覆盖大多数"放行）。含覆盖成员即构成「有差异」，**不得因无净增成员而不写盘**（见 §1 交付面）。

### 4.1 后日谈（L4）在施工层里的位置

L4 的改动**全部属步骤 4（写盘）**；步骤 3 的「插入计划」对其不适用 —— 后日谈不往宿主脚本里插行，而是**整脚本回填**（4 个 `SL_*.ws2`）＋**门控与路由**（Lua 与 `start.ws2`）。机制与偏移依据见 [afterstory-mechanics.md](afterstory-mechanics.md) §9，工序归属判据见其 §10。

| 项 | 落点 | 脚本 | 输入 | 构建期断言 |
|---|---|---|---|---|
| G1／G2 | `Script.arc` → `LegacyGame.lua` | `script/build/build_l4.py` | `backup/` 成员字节 | 目标字节序列（`49 c0 c6 8b`、`\x04<len=16>"openSceneSelect"\0`）逐一命中才改，全库唯一 |
| G3 | 裸 `RIO/SL_*.ws2` | `script/build/convert_sl_ws2.py` | 原版裸 `RIO/` | Steam 表回读：指令数／操作码／操作数／尾部一致 ＋ 跳转目标落位 |
| G4 | `Rio.arc` → `start.ws2` | `script/build/build_l4.py` | `backup/Rio.arc` | 解码后偏移 5 的 `00`→`01`；其余成员逐字节不变 |
| G5 | `zh-CN/Rio.arc` → 4 个 `SL_*.lng` | `script/build/build_l4.py` | `resource/fan_cn/SL_*.json`（875／851／714／788 槽） | `encode_lng`→`parse_lng` 逐槽回读 ＋ 归档回读等于内存 blob |
| G6 | `Script.arc` → `ArcFileName.lua` | `script/build/build_l4.py` | `backup/` 成员字节 | 常量追加在末尾 ⇒ 既有索引不变；插入块内跳转全为块内相对；graphics +66／sound +34 条数核对 |
| G7 | `PVOICE.arc`／`PCHIP.arc`（裸归档） | `script/build/build_l4.py` | 原版根目录裸归档 | 整档复制，成员数与字节数核对 |
| G8 | `SE.arc` +3 | `script/build/build_l4.py` | 原版 `PSE.arc` | 逐名断言「原版有、Steam 无」 |
| G9 | `GRAPHIC.arc`（**L4 不写盘**） | `script/build/build_l4.py --verify <产物目录或 GRAPHIC.arc>` | 产物 `GRAPHIC.arc` ＋ 原版／`backup/` 基线 | 逐名断言 33 名在位 ＋ 名单未漂移（原版有、Steam 基线无） |
| G10 | `zh-CN/Rio.arc` → `NameTable.txt` | `script/build/build_nametable.py` | `backup/zh-CN/Rio.arc` 官方表 + `resource/fan_cn/NameTable.json` | 官方条目保序且值不被改写；`SL_*` 用到的 8 个日文名牌键逐一在表 |

**现状与接口**：L4 的构建器 `script/build/build_l4.py`（`script/build/convert_sl_ws2.py` 供 G3 转码）输出到中间树 `tmp/_l4/asset/`（`RIO/` 放 G3 的裸脚本），从 `backup/` 起底、可复现（跑两次逐字节一致）。原版发行目录**不进版本库**，两个 L4 构建器按 `--orig-dir` 或环境变量 `IFMH_ORIG_DIR` 取用（口径见 [restoration-targets.md](restoration-targets.md)「素材来源」），未提供即拒绝运行；主线写盘器只认 `IFMH_ORIG_DIR`。

**并入方式已定为 §2 硬纪律 4 的①**：`script/build/build_patch.py` 先跑 `build_l4.py`（幂等），再单趟写全部共享归档，重叠的 3 个归档不出现两趟写盘：

| 归档 | 主线写盘器从 L4 中间树取什么 |
|---|---|
| `Rio.arc` | 只取 `start.ws2`（G4），其余成员由主线自己重建 |
| `zh-CN/Rio.arc` | 只取 4 个 `SL_*.lng`（G5）与合并后的 `NameTable.txt`（G10） |
| `SE.arc` | 需求并集含 L4 的 3 个独有 SE（G8，源为原版 `PSE.arc`） |
| `Script.arc` / `PVOICE.arc` / `PCHIP.arc` / 裸 `RIO/` | L4 独有交付，整份收割进 `asset/` |

**判给本体线的前置项**（判据＝引用面，逐项实测见 [afterstory-mechanics.md](afterstory-mechanics.md) §10.1）：33 张 `.pna`（G9，全部被原版主线脚本引用 ⇒ L4 不搬运）、`se43b`（G8 的三分之一）、日文名牌键全量合并（G10 的条目来源 `resource/fan_cn/NameTable.json`）、原版→Steam 的 WS2 编码转换（G3 的工序）。L4 的净自有交付＝门控与路由（G1／G2／G4／G6）＋后日谈独有资源（G7、`T_se91`、`pw129_4`）＋ FD 文本层（G5）。

**后果**：L4 的输出树不含 `GRAPHIC.arc`，因此它**不是**一份可完整实机验证的后日谈 —— 立绘缺失会让 `st01` 等槽报 `サブプレイヤーが存在しません`。后日谈的实机与验收一律跑在本线产物上（`python script/build/build_l4.py --verify <产物目录>`）。

## 5. 验收

1. **归档完整性**（`tool/arcbuild.verify()`，含无 null padding）；`asset/` 的归档集合**等于交付名单**（不含无差异归档），资源配对对未交付归档回落 `backup/` 解析
2. **调用链完整性**（跳转目标全部可达；A-1 的 5 处跳转已恢复）
3. **成就触发点完整性**：Steam 的 **922 处 / 51 脚本**调用 + **29 处 `0xF0`** 逐点核对，**指令与成就 id 均不变**，一处不少、不新增、不重算
4. **资源配对正确性**（插入段引用的原版名 → 产物成员，逐个可解析；同名冲突由覆盖接管 ⇒ 名字不变即可解析）；图像同名冲突逐名可追溯处置（`action=overwrite` 子集 → 覆盖名单逐名认领，**不进改名表**，缺一即中止；`class=reuse` 子集 → 逐个有**存活格核对结论**，需改写的格已在台账 `rebind`）
5. **改动面收敛核实**：`backup/` 未被写入；判定表 `action=overwrite` 子集**之外**的 Steam 原有成员逐字节未被替换；**覆盖成员**产物字节＝原版成员字节（逐名断言）、同帧 `B`/`S` **成组**处置、只换内容而**成员名与表位置不变**（脚本引用与成就面零改动，除台账登记的顶包存活格调点改写）；覆盖名单条数与实际替换次数**逐名对齐**
6. **可复现性**：从 `backup/` 起底跑两次，归档**逐字节一致**
7. **实机测试**（关键场景：A-1 的 5 个整脚本入口、A-2 的插入点前后；后日谈入口 = `mainmenu` 调 `openAfter` → `start.ws2` 置 `flag 1000` → `flag 126` 路由取 `PCHIP`/`PVOICE` 资源）
8. **交付项完整性**：构建期名单逐名断言，不以覆盖率代替 —— L4 自有交付为 `SE.arc` 含 3 个 SE、`zh-CN/Rio.arc` 含 4 个 `SL_*.lng`（875／851／714／788 槽）且 `NameTable.txt` 含 `SL_*` 用到的 8 个日文名牌键、裸 `RIO/` 含 4 个转码后的 `SL_*.ws2`；**端到端验收**为产物 `GRAPHIC.arc` 含 33 张后日谈 `.pna`（`python script/build/build_l4.py --verify <产物目录>`，L4 不搬运）
9. **文本-语音-CG 三元组一致性**（`script/verify_sync.py`，见 §4 第 6b 步）：还原行在产物上的 (文本, 语音, 画面) 逐槽无错位、覆盖成员字节＝原版；玩家可见面的每一条"画面／立绘／BGM 与期望不符"都要**归因到位**（删格残留／改写点），**未归因读数必须为 0**；承载图 1:1 块逐对过内容面核对，命中即按**还原缺口**处理（判据与盲区见 [lessons-learned.md](lessons-learned.md) §26）

## 6. 已确认的技术结论

| # | 结论 |
|---|---|
| V-1 | **两版游戏使用相同引擎，资源互通** ⇒ 原版资源可直接复用，无需重编码 |
| V-2 | 同名内容差**一律整名覆盖**：除重编码噪声（不动）外，一律用原版成员字节替换 Steam 同名成员——继承原名、不改脚本引用、不保留 Steam 版画面，**不设引用面门槛**。**画面和谐有两种形态**：在原版底图上重画遮挡、以及**取景变化**（放大裁切以去掉裸露）。**顶包（Steam 那张实为原版另一帧的副本）也不隔离改名**：覆盖把该号位收回原版自己的画面，只有**还原后仍保留的 Steam 格**在那个节拍对齐到别的帧时，才把**那一个显示调用点**改写成那一帧的原版名（台账 `rebind`）。**被还原掉的行不再消费 Steam 素材** ⇒ 被删格与整段被原版行替换的区间不触发改写；鉴赏／回想页（`CG_PAGE*`）的引用不入判据；**引用点数不作判据**，只当报警量。号段（`9X` = L1–L3、`8X` = L4）只服务**真正的新增资源**，覆盖与顶包都不占号段。判据与连带规则详见 [resource-naming.md](resource-naming.md) |
| V-3 | `LAYER_ORDER` 重排语义两版相同，不构成障碍 |
| V-4 | 成就由开发者与 Steam 共同管理，本补丁**只保留触发点**：指令与成就 id 原样保留，**不新增**任何触发指令；被删 5 脚本内的 332 处 CG 位点**不补钩子**（Steam 本身未在此设成就） |
| V-7 | **画面维度的删减不体现在文本差分里**：和谐改画的两侧行数、跳转、语音 token 全一致，差分扫描完全看不见 ⇒ 只能靠图像比对定案，判据为五步「内容哈希筛 → 全分辨率逐像素 → 缩略图全库最近邻 → 放大裁切匹配（取景变化）→ 顶包确认 + 存活格核对」（证据复算＝一次性比对脚本，落在 `tmp/`、不入库）。**尺寸差与体积差不能代替判定**；**最近邻命中别的帧单独不能定号位复用**——放大裁切式和谐同样会命中别的帧，顶包只由**全分辨率逐像素的副本级距离**证实。**引用点数不作判据**（无论在 Steam 原生脚本还是还原后产物上数），异常点数只当报警量；顶包的后果不是"要隔离"，而是**要在存活格上改写那一个显示点**（见 [resource-naming.md](resource-naming.md) §2） |

## 7. 待办

- **V-5 插入点与形态逐段定案**：`resource/carrier_map.json` 里标 `ambiguous` 的中部缺口（原版行 4,769 / Steam 格 1,115）需逐段读原文定形态。
  **判据**：头部缺口机器可定（按尾对齐，多出的原版行在头部 ⇒ 删除）、尾部缺口按头对齐；**中部缺口两侧条数不等时机器不猜**。
  - **未覆盖实例**（按原版 CG 调用点反查出的缺口形态）：`KOT_003` 原版行 1186 的 `KOT_12_016S` 显示点落在未合并的相邻插入段之间，还原流里没有任何位置承载它；同脚本 1081–1105 一段走的是「Steam 自有显示点」而非插入块，该段的号位是否等价于原版对应行**未逐行核对**。⇒ 缺口定案除按行数对齐，还须核对**原版 CG 调用点在还原流里是否有显示位**。
  - 已定案的示例：`YOR_004` seg0（原版 0–84）⇒ 插入点 = Steam **第 0 槽之前**；`AGE_006` 原版 284–304 ⇒ **改写 + 整段删 + 压缩概述混合**，插入点在 Steam 槽 278 与 279 之间。
- **V-6 B 清单重判**：早期按「内容存在性探针」分出的 C 型「新增⇒保留」与小规模 D 型，须按 [restoration-targets.md](restoration-targets.md)「判定标准」重判。
- **V-8 画面还原（L1-G）的工序接入（已落地）**：判定表 `resource/censor_map.json`／`voice_conflict_map.json` 的 `action=overwrite` 子集经 `script/build/build_restore_plan.py` 进 `resources.overwrite`，由 `script/build/build_patch.py` 逐名**整名替换**（名单数＝替换数断言，纯覆盖也触发写盘），`script/final_verification.py` 落「覆盖字节＝原版」「名单数＝替换数」两条断言；改名路线已停用（`RENAME_ROUTE_RETIRED`），插入段照抄原版名。判据见 §2 硬纪律 2 与 [resource-naming.md](resource-naming.md) §1–§3。
- **V-9 删格残留的处置（裁定＝删该行演出 ＋ 只删文本与名字框 ＋ 画面走字节覆盖）**：删格的定义是「被删槽的 `14` ＋**该行的演出前缀区**（上一条 `14` 之后 → 本行 `14` 之前）内除 `KEEP_OPS` 外的全部指令 ＋ 邻接 `15`（守卫生效者）」（`tool/writer.drop_units()`）。`KEEP_OPS = {01,02,05,06,07,09,0B,0F,15,F0,FF}`（流程控制／菜单／状态写入／名字框／成就／终结符），`04` 只保留非 `LAYER_ORDER` 调用 ⇒ **纯表现**（语音 `2e`+`28`、显示 `33`/`34`、BGM `1e`、图层定位 `46`、特效…）随该行一起删；**状态写入、跳转、成就调用一律逐字节保留**。原因：残留排在插入的原版块**之后**执行，会把画面/BGM 顶回 Steam 素材并造成无对白连播语音（见 [lessons-learned.md](lessons-learned.md) §16）。
  - **画面**＝归档字节层 ＋ 删格层。同名内容差整名覆盖后，**保留下来的 Steam 显示点加载的就是原版画面**；被删行的显示指令已随演出前缀区删除 ⇒ 不再有「残留把画面顶回 Steam」这一路。唯一要按调用点处理的是**顶包名**（判定表 `class=reuse`）：覆盖把该名收回原版自己的画面，而 Steam 的**存活格**在那个节拍其实要放的是**另一帧** ⇒ 只把**那一格**的显示指令（`0x33`／`0x34` 的操作数）改写成那一帧的原版名，**禁止全局替换**（同一名字在不同宿主／段落里指两侧不同图）。
  - **语音**＝随演出前缀区删除：被删行的 `0x28`（连同其 `0x2e` 头）整条摘掉，不按名点名、不按格删、**不删语音文件**。原版独有的配音走**导入**（新增成员）。验收＝产物里不得出现「同一格携带多条**残留**语音触发」（无对白连播；合唱行是原版自身形态，不算），且 `R.residue_voice` ＝ 0。
  - **演出**＝只补不删（**仅对插入行**）：Steam 骨架没带上的原版随行演出（立绘/背景/CG）随插入的原版块**按行位注入**，注入块内每个立绘绑槽若与**此刻在屏的同族**（名前 4 字符）撞别的槽，先补一条清槽指令再绑——**只清注入来源占的槽**，Steam 骨架自有的同族双槽是原生行为，一律不动。插入块跨度＝`[o14[r0-1]+1, o14[r1]+1)`，**不携带 r1+1 的演出前缀**（携带会让同一触发连发两次，见 [lessons-learned.md](lessons-learned.md) §16）。
  - **排除的口径**：整格删除（连带删掉格内状态写入与成就所在指令）——收益只是极少数顶包名的存活格显示点（那一点走调用点改写即可），代价是变量/流程面失去等价写并要求操作码分级表＋状态等价闸两期工程；纯删除段更不动（没有原版块接手，删了就没画面与配音）。
  - **施工前置**（任一不成立即不得声称画面／语音还原生效）：
    1. **覆盖名单接入写盘链**（＝V-8，已落地）：覆盖没落盘，残留显示点显示的就还是 Steam 那张，本项全部结论失效。
    2. **残留显示点逐名分类，且按两个维度分诊**：先按**处置类别**（覆盖名／噪声名）分桶，再按**名字来源**复核——名字在原版归档里**有同名成员**者由字节层消化，**查无同名**者（Steam 自有号段）落「回退面」⇒ 按缺陷处理。**核对面只收顶包名（`class=reuse`）落在存活格上的调用点**，逐点登记宿主＋位置＋该点应有的画面。
    3. **语音点名清单与删后校验**：点名依据＝被删文本行的配音 ＋**被删格内保留下来的 `0x28` 触发**；删完回读，存活文本格不得再挂被删配音，已删格不得残留名单内的 `0x28`，且产物里**不得出现「相邻两条语音触发之间没有 `14`」的段**（无对白连播）。
    4. **注入块的槽位终态检查**：还原流末态不能有「同族两槽同屏」；清槽指令只能由注入触发，不得改动骨架原生绑槽次序。
    5. **名字框守卫**：`drop_units` 因守卫而存活的邻接 `15` 不得被本轮删除集扩大。
    6. **实机验证一次**：覆盖后的 CG 显示、注入后的立绘位置与配音同步，按关键场景跑图。
  - **验收连带**：成就基线维持**四连逐字节原位**（`doc/acceptance-criteria.md`「成就触发点完整性」、[engine-mechanics.md](engine-mechanics.md) 保留纪律 3，显示头 `0x33` 不摘）；`script/final_verification.py` 需落「顶包名的存活格逐个有调点改写结论」「语音点名删净」「注入块同族不双槽」三条断言。详见 [lessons-learned.md](lessons-learned.md) 第 20 条。
- **转换器缺口已补齐**：`CONV` 已补 `0x1c`(end1)/`0x35`(end1)/`0x56`(end4)，依据 = 两版 256 项格式表**全量差分**（实质内容差恰 9 条，无遗漏；SL 输出 md5 复验逐字节不变）。Steam 表线性解析失步的 8 个成员（`CG_PAGE09-12`/`CO1_018`/`CO2_005`/`HUT_005`/`Pan.dat`）**均不在本体写盘目标与 orig 提取源名单内**（CG_PAGE 延后、CO1_018/CO2_005 无台账写项、HUT_005 台账全 keep、Pan.dat 非 WS2）；实际需解析的 47 个 orig 源中仅 `HUT_005` 原版失败且无需提取。`tool/ws2dis.disassemble()` 的 `ok` 标志只校验尾部长度、查不出流中部失步——管线各闸不把它当可解析凭证，一律以「Steam 表回读 + 指令数/操作码清单/跳转落位」为准。

## 8. 与既有产物的关系

- **文本层**（`resource/fan_cn/*.json` + `NameTable.json`）**就是** `resource/` 的输入表之一，直接沿用；`.lng` 与合并后的 `NameTable.txt` 只是装载形态，按 §4「派生形态不留档」在写盘时现做。
- `tool/` 已有 `arcbuild.py`（归档读写 + `verify()`）/ `ws2.py` / `ws2dis.py` + `ws2fmt.txt` / `scriptext.py` / `lng.py` / `pna.py` / `fancn.py` / `textfix.py` / `v5lib.py`，与参照项目同源，可直接扩展。
- **施工层已在链**：§4 表里每一步都有脚本——主线 `script/build/` 下的 `build_carrier_map.py`／`build_rename_map.py`／`build_restore_plan.py`／`build_patch.py`，顶层的 `script/generate_payload.py`／`script/final_verification.py`／`script/verify_sync.py`（§4 第 6b 步），L4 侧 `script/build/build_l4.py`（写盘 G1／G2／G4～G8／G10，G9 只做端到端验收）、`script/build/convert_sl_ws2.py`（G3）、`script/build/build_nametable.py`（G10 唯一合并出口），发布链 `script/pack.sh` + `tool/install.py`。结构写盘器为 `tool/writer.py`，反汇编由 `tool/ws2dis.py` 承担（操作数格式表从引擎 `off_553EC0` 导出，对本作权威）。
- **机检不覆盖的一项**：§5 第 7 项**实机测试**（关键场景＝A-1 的 5 个整脚本入口、A-2 插入点前后、后日谈入口链路）只能手工跑图，不由 `script/final_verification.py` 断言。
