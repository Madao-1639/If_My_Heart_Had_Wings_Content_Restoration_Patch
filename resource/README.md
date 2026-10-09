# resource/ 数据索引

本目录是补丁的数据层：文本层底稿、中文文本产物、还原判定台账（文本差分与图像同名冲突）、施工计划。目录条目写**文件结构**，单表条目写**表结构**，并标出生产者与消费方；判读口径、工序与验收读数一律见 `doc/`，本文件不重复。

## resource/corpus/ —— 文本层底稿

**文件结构**

- `jp/{SCRIPT}.json`：来自原版 `Rio.arc` 的逐条目日文。
- `jp/RIO/{SCRIPT}.json`：来自裸 `RIO/` 目录的逐条目日文（含主线脚本、后日谈 `SL_*` 与 `start.json`；`start` 无对白条目）。
- `zh/{SCRIPT}.json` 与 `zh/RIO/{SCRIPT}.json`：与 `jp/` 同一套脚本名、同一布局的中文条目底稿。
- `pairing.jsonl`：原版文本行与民汉译文的位置对齐表，一行一条。
- `review_fixes.jsonl`：语境层改动表，一行一槽。

### jp/、zh/ 的条目底稿

**表结构**（美化 JSON，一个脚本一份文件；`zh/` 文件是多段拼接，`json.load` 会报 Extra data，须用 `json.JSONDecoder().raw_decode()` 取首段）

| 字段 | 类型 | 含义 / 取值 |
|---|---|---|
| `script` | str | 脚本名（不含扩展名） |
| `source` | str | 条目来源：`jp/` 为 `Rio.arc` 或 `RIO`；`zh/` 为民汉表 |
| `total` | int | 条目数（= 该脚本的 `.lng` 槽数） |
| `texts[]` | list | 逐条目：`lng_idx`（int，槽位）、`text`（str，含 `%K`/`%P`）、`jp/` 另带 `text_with_name`、`char_name`（多为 null） |
| `matched` / `unmatched` | int | 仅 `zh/`：与原版行的键匹配计数 |

`zh/` 只为对白行建条目，因此它的逐脚本 `total` 比 `fan_cn/` 少掉的正是该脚本的 ctrl/menu/flag 行；条目数以 `doc/script-text-extraction.md` §3.5 的 count_parity 口径为准。

**生产者**：按条目导出的底稿，入库作对照存证。**消费方**：`tool/v5lib.py`（原版行文本，用于逐块判读与引证核验）、`script/corpus/build_fan_translations.py`（读 `zh/` 的 `total` 作条目数诊断对照）。

### pairing.jsonl

**表结构**（一行 = 一条原版文本行）

| 字段 | 类型 | 含义 / 取值 |
|---|---|---|
| `script` | str | 脚本名 |
| `kind` | str | 行类，`dlg` / `ctrl` / `name` / `menu` / `flag`（形态与建槽规则见 [script-text-extraction.md](../doc/script-text-extraction.md) §1.2） |
| `idx` | int \| null | 槽位号：`dlg`/`ctrl` 取脚本内 idx，`menu`/`flag` 取选项或 `FLAG_CHECK` 的 id，`name` 行为 null |
| `off` | int | 该行在解码流中的字节偏移 |
| `seq` | int | 按 `off` 排序后的脚本内行序（0 起） |
| `jp` | str | 原文（cp932 解码） |
| `cn` | str | 对齐到的译文；`src` 为 `need-translate` 的行是空串，由构建阶段就地补译，不落原文 |
| `src` | str | 配对来源：`positional`（位置对齐）/ `crc-tail`（按 CRC32 在尾部残量里认领）/ `ctrl`（清屏行）/ `need-translate`（无译文） |
| `crc` | int | 引擎口径的查表键（`crc32_signed`，有符号） |

**生产者**：`script/corpus/align_corpus.py`。**消费方**：`script/corpus/build_fan_translations.py`（出包）与只读复检脚本。

### review_fixes.jsonl

**表结构**（一行 = 一个被语境层改写的槽位）

| 字段 | 类型 | 含义 / 取值 |
|---|---|---|
| `script` | str | 脚本名 |
| `idx` | int | 槽位号 |
| `kind` | str | 行类，与 `pairing.jsonl` 同行类口径 |
| `from` | list[str] | 来源层名。只记**最终生效层**：同一槽位被后层改写时不保留前层名，所以各批改动的落地计数会大于该层在表内的现存槽数 |
| `cn` | str | 终值文本 |

**生产者**：`script/corpus/merge_fixes.py`（全表按规则重建；新增改动按槽位增量并入）。**消费方**：`script/corpus/build_fan_translations.py`（语境层套用与出包门禁）、只读复检脚本。层名清单与合成规则见 [script-text-extraction.md](../doc/script-text-extraction.md) §3.2。

## resource/fan_cn/ —— 中文文本产物

**文件结构**

- `{SCRIPT}.json`：逐脚本一份，覆盖主线脚本与后日谈 `SL_*`。
- `NameTable.json`：说话人名译名表。
- `manifest.json`：产物清单与统计项。

引擎装载形态（`.lng`、`NameTable.txt`）不在此留档，构建时从这些 JSON 现做并封进归档。

### {SCRIPT}.json

**表结构**：`{"<槽位号>": "中文文本"}`，键是十进制字符串、与脚本 `.lng` 槽位一一对应，值保留 `%K`/`%P` 标记；说话人名不进正文（在 `NameTable.json`）。

### NameTable.json

**表结构**：`{"%LC<日文名>": "中文显示名"}`。日文名会直接上屏，因此该表同样进出包门禁。

### manifest.json

**表结构**

| 字段 | 类型 | 含义 |
|---|---|---|
| `generator` | str | 产出脚本 |
| `pairing` / `pairing_doctrine` | str | 对齐表路径 / 按位置而非按键消费的口径声明 |
| `text_layer` | dict | 机械层与语境层的规则归属 |
| `key` | str | `.lng` 的 XOR 密钥（`"0x88"`） |
| `conventions` | dict | 各行的建槽约定（对白、菜单、FLAG_CHECK、清屏行） |
| `totals` | dict | 全库计数项（槽位数、各行为数、译名数、改动表已应用槽数等） |
| `scripts` | dict | 逐脚本计数项 `{size, n_dlg, n_menu, n_flag, n_ctrl, n_name_row, n_unique_name, terminator_aligned, bracket_balanced, soft_break_diff, src}` |
| `acceptance` | dict | 验收项：与旧提取的条目数对照、门禁清单 |

**生产者**：`script/corpus/build_fan_translations.py`（脚本 JSON 与 `manifest.json`）、`script/build/build_nametable.py`（`NameTable.json`）。**消费方**：`tool/fancn.py`（装载与复检的统一读取口）、只读复检、`script/build/build_restore_plan.py`（插入行取中文文本）、`script/build/build_l4.py` 与 `script/build/convert_sl_ws2.py`（`SL_*` 的装载形态与译名合并）。

## resource/carrier_map.json —— 承载图

**表结构**：顶层 `{脚本名: 记录}`，记录为

| 字段 | 类型 | 含义 |
|---|---|---|
| `script` | str | 脚本名 |
| `orig_rows` / `steam_slots` | int | 两侧行／槽位总数（dlg/ctrl 口径） |
| `orig_tokens` / `steam_tokens` | int | 两侧语音 token 数 |
| `anchors` | int | 唯一 CRC32 锚点数 |
| `blocks[]` | list | 顺序铺开的对应块 |

块的字段随 `kind` 变化：

| `kind` | 字段 | 含义 |
|---|---|---|
| `anchor` | `orig`、`steam` | 一一对齐的锚点行／槽，`orig` / `steam` 是闭区间 `[起, 止]` |
| `match` | `orig`、`steam`、`form`、`anchor?` | 段对齐；`form` 记对齐形态（`1:1`、`1:1（头对齐）`、`1:1（尾对齐）`），`anchor` 为区间内锚点情况的说明文本 |
| `ambiguous` | `orig`、`steam`、`form` | 中部缺口，`form` 写明哪侧多几行、需逐段读原文定形态 |
| `orig_only` | `orig`、`form` | 仅原版侧有行（Steam 删） |
| `steam_only` | `steam`、`form` | 仅 Steam 侧有格（新增） |

只收录两侧都在的脚本；Steam 侧整脚本缺失的 A-1 脚本与后日谈 `SL_*` 不在图内，系统／背景类无对白脚本也在表内。差分净差口径见 [restoration-targets.md](../doc/restoration-targets.md)。

**生产者**：`script/build/build_carrier_map.py`。**消费方**：`tool/v5lib.py`（唯一直接读取口，判读批次生成与校验器都经它）。

## resource/carrier_quirks.json —— 承载图已知假锚/拆行判定表

**定位**：承载图只按 **token 值相等**钉锚，不读文本 ⇒ 会出现「同名 token、两句内容」的**假锚**（见 [restoration-targets.md](../doc/restoration-targets.md)）。本表把「台账的决定」与「承载图的机械配对」的差异**显式记账**：每条 = 一个已知不良机械配对 + 真相 + 台账已落的动作，供只读对账用；**本身不含任何处置动作**（产物仍以 `resource/adjudication/` 为准）。

**表结构**：顶层 `meta`（口径 + `kinds` + `ledger_rules` 枚举）与 `quirks[]`：

| 字段 | 类型 | 含义 |
|---|---|---|
| `script` | str | 脚本名 |
| `kind` | str | ∈ `false_anchor`（锚对两侧不是同一句）／`missing_seam`（原版行夹在两段插入之间被漏，机械上被错槽「承载」）／`split_row`（一行被 Steam 拆两格，零删减） |
| `mechanical` | dict | 承载图里的机械配对 `{orig:[行], steam:[槽]}` |
| `truth` | str | 实际对齐/原因 |
| `ledger` | str | 台账已落的动作（条目 id/描述） |
| `ledger_rule` | str | 对账规则 ∈ `slot_dropped`／`text_override`／`row_inserted`／`none` |
| `evidence` | str | 证据文件（`tmp/` 或 `doc/`） |

**生产者**：人工（锚点全面抽查）。**消费方**：`script/checks/check_carrier_ledger.py`（只读）。

## resource/adjudication/ —— 判读台账

**文件结构**：逐脚本一份 `{SCRIPT}.jsonl`，另有 `rereview_{线名}.jsonl` 存复判件。主表一行 = 一个判读块，字段：

| 字段 | 类型 | 含义 / 取值 |
|---|---|---|
| `script` | str | 脚本名 |
| `block_orig` / `block_steam` | list[int] | 本块覆盖的原版行区间／Steam 槽位区间，闭区间 `[起, 止]`；起大于止表示该侧无行 |
| `cells[]` | list | 逐槽判定：`slot`(int)、`action`(str ∈ `keep` / `drop` / `rebind`；**`text` 已废弃**)、`form`(str，处置名称)、`quote`(str，该槽文本的逐字引文)；`rebind` 另带 `bind_orig_row`(int，改绑到的原版行)，部分再带 `orig_quote`(str，该行原文引证)；**民汉文本覆盖不再是独立 action**，而是保留格的属性：`action=keep` + `text_override:true` + `bind_orig_row`(int，该槽 zh 文本改用的原版行民汉)，**脚本指令不动**（口径更新后的实际形态；计划器遇 `action=text` 直接报错） |
| `inserts[]` | list | 整段插回：`after_slot`(int，插在哪一槽之后)、`orig_rows`(list[int]，闭区间)、`form`(str)、`quote`(str) |
| `orig_waived` | list[list[int]] | 判定不还原的原版行闭区间 |
| `verdict` | str | 一句话裁定（自由文本，不是枚举） |
| `note` | str | 判据说明 |

复判件字段为 `script` / `block_orig` / `block_steam` / `scene`(str，同拍／复述等场景类别) / `current`(str，原裁定) / `action`(str ∈ `stands` 等) / `reason`(str)，只作判读证据，消费方按 `rereview` 前缀跳过。

**生产者**：人工逐块判读的交付（块与承载图相符、槽位与原版行全覆盖且每处恰一次、引文逐字命中）后落地。**例外**：等长 `match` 块复审落地的 `EQR_*` 条目（71 块，口径见 [restoration-targets.md](../doc/restoration-targets.md)「等长 match 块的复审与成因分诊」）走另一条验证链——交付方逐块人工读 ＋ 验收方四语对照逐块亲读；其 `cells` **只列动作槽**（`action=keep` + `text_override:true` + `bind_orig_row`，未列槽沿用承载图 keep 口径）、`quote` 留空（引文在评审交付物的 evidence/ 里），不适用常规全覆盖口径（该口径仍只认 `keep/drop/rebind` 且要求全覆盖，对这些条目会报错，属已知豁免）。**消费方**：`script/build/build_restore_plan.py`（`cells` 的 `drop` 与 `inserts` 合成删槽／插入行集；`keep+text_override` 合成 zh 交付的槽位文本覆盖，经 `plan.text_overrides` 声明并由 `script/verify_sync.py` 的 B3 核对）、`script/build/build_rename_map.py`（`inserts` ∪ `rebind` 的原版行号界定资源引用面）。裁定标准见 [restoration-targets.md](../doc/restoration-targets.md)「判定标准：差分形态与采用口径」。

## resource/rename_map.json —— 号段候选表（**改名路线已取消，本表恒空**）

**定位**：两侧同名的冲突一律**整名覆盖** ⇒ **不改名、不进本表**；顶包也只改写那一个存活调用点。号段（`9X`／`8X`）只服务**真正的新增成员**，而新增成员按 [resource-naming.md](../doc/resource-naming.md) §1 第 4 条**直接继承原版名** ⇒ 本体还原侧当前**无号段用途**。故本表恒出空的 `voice`／`sprite`／`mos`／`est`，只保留**诊断清单**（冲突面与引用面读数），消费端的取名映射（`plan.names`）同步停用、恒为空。历史遗留的图像／`.MOS`／语音条目已清除（原「待撤销项」已执行）。

**表结构**

| 字段 | 类型 | 含义 |
|---|---|---|
| `est` / `voice` / `sprite` / `mos` | list | **恒为空**。若「号段编号」这一潜在用途被启用（[resource-naming.md](../doc/resource-naming.md) §8），此处才会重新出现条目：含 `orig`（原名）、`patch`（补丁内名）、`source_archive`（归属归档），立绘条目另带 `role` |
| `unparseable` | list | 解析不出补丁名或该类号段已用尽、因此未能自动改名的项；条目含 `name`、`archive`，另带 `referenced_as`（引用形态）或 `reason`（如号段耗尽）。**恒为空**（无规则在跑） |
| `unused_conflicts` | list | 两侧同名冲突中**未被还原内容引用**的历史桶（候选按**文件体积差**筛，该口径已作废）。**不作任何处置依据**——图像同名冲突一律看 `censor_map.json`（非噪声者整名覆盖，**不设引用面门槛**） |
| `meta` | dict | `retired`(bool，改名路线是否已取消)、`conflict_names`(int)、`referenced_names`(int)、`restored_scripts`(list[str])、`reference_scan`(str，引用扫描的指令口径)、`rule`(str，现行口径)、`segment`(str，号段分配)、`spec`(str，规范文档) |

**生产者**：`script/build/build_rename_map.py`（`RENAME_ROUTE_RETIRED` 开关；保留号段分配代码作回退位，但恒不产出条目）。**消费方**：`script/build/build_restore_plan.py`（只读它做互斥闸——判定表 `overwrite` 成员不得出现在本表，见 [resource-naming.md](../doc/resource-naming.md) §7.5）。**取名口径**（先于一切写盘）：插入块里的资源名**照抄原版脚本里的名字即为正确**——覆盖只换同名成员的内容、不改成员名 ⇒ 原名在还原后的归档里承载的就是原版画面。

## resource/censor_map.json —— 图像同名冲突判定表

**定位**：写盘器**唯一的覆盖依据**——未登记的成员不得被替换。一行 = 一个两侧同名（大小写折叠对齐）而字节不同的图像成员。

| 字段 | 类型 | 含义 / 取值 |
|---|---|---|
| `archive` / `name` | str | 归属归档、Steam 侧成员名（覆盖后**名与归档表位置不变**，只换内容） |
| `orig_name` | str | 原版侧成员名（取字节的来源，大小写可能与 `name` 不同） |
| `class` | str | 类别 ∈ `censor`（同名两侧是**同一张画面**、Steam 改过画——叠加遮挡或放大后裁掉裸露区域的取景变化）/ `reuse`（**顶包**：Steam 那张其实是原版另一帧的副本 ⇒ **动作仍是整名覆盖**，差别只在要对该名做**存活格核对**：还原后仍保留的 Steam 格里若那一拍要对上的是别的帧，改写那一个显示调用点）/ `noise`（重编码噪声） |
| `action` | str | 处置 ∈ `overwrite`（整名覆盖，非噪声者的**唯一**动作）/ `keep`（噪声，不动）。**没有改名类动作**——隔离改名路线已取消 |
| `referenced` | bool | 该成员是否被还原段落引用（按还原流的指令操作数口径）。**不改变 `action`**（覆盖零代价，引用与否都覆盖），只作核对与"补资源清单"的参考 |
| `series` | str | 所属系列键（`<归档>/<系列前缀>`，前缀＝角色_场景段；单帧自成一判时取帧基名），人工结论见顶层 `series` |
| `frame` / `pair` | str / list[str] | 帧基名（去 B/S 变体后缀）；本表内同帧的**其他**成员名。判定与处置按帧成组：`pair` 为空表示另一变体在两侧都不存在，只有该名需处置 |
| `group_lock` | bool | 同帧成组传导标记。现行方针下同帧成员的动作天然同向（非噪声一律 `overwrite`、噪声一律 `keep`）⇒ **恒为 false**，只保留字段位 |
| `dims` / `size_diff` | dict / bool | 两侧画布尺寸；`true` 时逐像素比对已把原版按 Steam 尺寸对齐 |
| `big_pixels` / `big_ratio` / `bbox` / `mean_diff` / `max_abs` | int / number / list[int] / number / int | 逐像素证据：大差（逐通道绝对差 > 16）像素数与占比、差异外接框、大差像素上的均值差、全图最大差 |
| `nearest` / `same_name_distance` / `margin` | dict / number / number | 原版同归档全体图像里最相似成员及其距离、同名成员自身的距离、二者差。**只作检索入口**：最近邻属另一帧**不**构成号位复用（放大裁切式和谐同样如此） |
| `zoom` | dict | 放大裁切匹配读数：`scale`（最优倍率）、`offset`（取景窗左上）、`mad`（窗内灰度 MAD）、`direct_mad`（1.0 倍左上对齐直比，尺寸不同为 `null`）、`window`（取景窗/画布尺寸）。`scale>1` 且 `mad` 远小于 `big` 级差异 ⇒ 同镜头的取景变化 |
| `alias` | dict | 顶包证据：`{name, frame, mad}`——最近邻属另一帧时的全分辨率灰度 MAD；达副本级重合（`mad < 1.0`）才成立，无顶包为 `null`。**成立时动作不变**（仍 `overwrite`），触发的是该名的**存活格核对** |
| `surviving_sites` | list \| 缺省 | **仅 `class=reuse` 有**：存活格核对结论，逐点一条 `{script, slot, name_offset, steam_display, chan, plan, orig_row, orig_display[], decision, rewrite_to?, note, checks?}`。`decision` ∈ `rewrite`（对齐到的原版行显示**另一帧** ⇒ 改写该调用点，目标见 `rewrite_to`，`name_offset` 是**解码流内名字字节的绝对偏移**）／`cover_ok`（覆盖即正确：对齐到的原版行显示同帧，或该点是**被删格残留**、还原后不再消费 Steam 素材）。`checks` 记两道机器核对（`voice` 语音号归属、`text` 两侧互译）。无 `rewrite` 点 ⇒ 只覆盖、脚本一字不改。结论按规则定案后注入；`--emit-map` 按名保留 |
| `refs` | dict | 两侧 Steam 原生脚本内该全名的显示引用点数 `{steam, orig}`（`Rio.arc` + `Script.arc` 反混淆后按 ASCII 全名字节计数）。**已退出判据**，只作报警量：点数异常提示回查对齐与计划区间，不改 `class` 也不改 `action` |
| `ambiguity` | str | 粗筛读数 ∈ `none` / `ref-overflow`（Steam 侧点数多于原版）/ `alias` / `alias+ref-overflow`。**不指向任何动作**（改名路线已取消）。顶包名的定案来自**存活格核对**：调用点分三类——**还原后仍保留的 Steam 格**（唯一约束来源）／**被删格残留**（不再消费 Steam 素材，不计入）／**原版插入段**（照抄原版名，由覆盖接管）；鉴赏页（`CG_PAGE*`）的引用不入判据 |
| `mos` | list[str] | 该成员在 Steam 侧的 `.MOS` 伴生成员名（只登记；**不随覆盖补入**） |
| `review` | str | 定案来源 ∈ `visual`（人工看图确认）/ `machine`（仅机器证据，未定案） |

顶层 `meta`：`spec`、`method`（五步判据）、`archives`（实际存在图像同名冲突的归档）、`class_values`、`actions`（两个动作的语义）、`gate`（非噪声者一律整名覆盖、噪声不动、**没有改名类动作**，以及"名单外不得改写"的门禁口径）、`excluded`（系统／引擎层归档为何不在表内）。顶层 `series` 按系列记 `class` 与人工读图说明（改画内容）。

**生产者**：一次性比对脚本（`tmp/scan_image_conflicts.py`，**不入库、不作工序输入**；只读比对，逐名输出证据与机械类别／动作；入库形态由同一脚本 `--emit-map resource/censor_map.json` 写出，**既有的人工定案按名保留**——`referenced`／`series`／`review`／`surviving_sites` 四者按名继承，类别被判据翻面的名字逐条报警 ⇒ 那些定案作废须重看），**人工逐张看图定案类别**；证据读数由该脚本复算，类别只认 `review`。顶包的**存活格核对结论**（`surviving_sites`）按规则定案后注入（机器出证据、结论按规则；见 [resource-naming.md](../doc/resource-naming.md) §3／§7.7）。**消费方**：`script/build/build_restore_plan.py`（`action=overwrite` 子集**逐名**进资源分派的 `overwrite`，`surviving_sites` 的 `rewrite` 点进 `reuse_rewrites`）、`script/build/build_patch.py`（**整名替换**同名成员 + 按调用点改写，**名单外不得改写**、名单数须与替换数逐名对齐）。判据与连带规则见 [resource-naming.md](../doc/resource-naming.md) §1–§3。

## resource/cg_site_rewrites.json —— 保留行事件 CG 显示点缺口表

**定位**：Steam 把原版**事件 CG** 的显示点换成**背景**时，两侧名字**不同** ⇒ `censor_map`（入口是「同名两侧字节不同」）与两条文本机检都看不见；若该行是保留 1:1，产物就照搬 Steam 指令、玩家看不到那张 CG（见 [lessons-learned.md](../doc/lessons-learned.md) §17）。本表逐条记账并驱动修复。

**表结构**：顶层 `meta` 与 `sites[]`：

| 字段 | 类型 | 含义 |
|---|---|---|
| `script` | str | 脚本名 |
| `slot` | int | 保留的 Steam 槽（应显示该 CG 的位置） |
| `orig_row` | int | 原版行（该 CG 的真正显示点） |
| `name` | str | 该 CG 成员名（原版侧） |
| `archive` | str \| null | 该成员在原版里的归档（信息性；实际补入由计划器的资源扫描决定） |
| `kind` | str | ∈ `missing`（产物缺该 CG）／`extra`（产物多出或张冠李戴的显示）；缺省按 `missing` 理解 |
| `reason` / `evidence` | str | 判据与证据 |

顶层 `meta.pending[]` 记**不宜由本表修**的站点（如 `AGE_007` s421：结构性重复），供回台账裁定。

**消费方式**：`script/build/build_restore_plan.py` 把每条按 **rebind 同形**落到计划——drop 该保留槽 + 插入该原版行（随行带入 `0x33` 显示指令），资源扫描再把该成员并入 `resources.copy`；计划里落 `plan.<host>.cg_sites` 供核对。

**生产者**：人工（语义评审 + 父级复算；判据：原版该行自有 CG 类 `\x33` 显示 ∧ 该槽为保留 1:1 ∧ 该名在 Steam 侧任何位置都未显示）。**消费方**：`script/build/build_restore_plan.py`。

## resource/voice_conflict_map.json —— 语音同名冲突判定表

**定位**：语音侧与 `censor_map.json` **同构**的入库判定表——写盘器覆盖语音成员的唯一依据。一行 = 一个两侧 `VOICE.arc` **大小写折叠同名、SHA256 不同**的 `.OGG` 成员。

| 字段 | 类型 | 含义 / 取值 |
|---|---|---|
| `name` / `orig_name` | str | Steam 侧 / 原版侧成员名（覆盖后**名与表位置不变**，只换内容） |
| `archive` | str | 归属归档（`VOICE.arc`） |
| `class` | str | 类别 ∈ `noise`（解码 PCM 实质相同 ⇒ 仅容器差）/ `recode`（同一录音被重编码／剪辑：最佳对齐后相关 ≥0.5、时长常变）/ `rerecord`（换录音：相关 <0.5） |
| `action` | str | 处置 ∈ `overwrite`（整名覆盖回原版字节）/ `keep`（`noise`，不动）。**没有改名类动作** |
| `steam_bytes` / `orig_bytes` / `steam_dur` / `orig_dur` / `d_dur` | int / number | 两侧体积与时长（秒）及其差 |
| `steam_vendor` / `orig_vendor` | str | OGG comment header 的 vendor 串 |
| `env_corr` / `pcm_corr` / `lag_ms` | number | 5 ms 包络粗对齐相关、1 采样精修后的原始 PCM 相关、最优滞后（ms） |
| `review` | str | 证据来源 ∈ `machine`（ffmpeg 解码 + 波形比对）/ `container-only`（无 ffmpeg 时退化为容器级判据） |

顶层 `meta`：`spec`、`producer`、`consumer`、`method`（判据全文）、`class_values`、`actions`、`gate`、`archives`；顶层 `summary` 记 `byte_diff` / `noise` / `recode` / `rerecord` / `overwrite` / `keep` 计数。

**判据**：两侧同名 ∧ 字节不同 ⇒ 解码 8 kHz 单声道 PCM → 5 ms 包络粗对齐 + 1 采样精修求原始 PCM 相关；**`noise` 需同时满足「相关 ≥0.98」与「时长差 ≤0.15 s」**（只看相关会漏判「同一录音被剪掉一截」——重叠段相关仍近 1，但时长差大，属内容差）。`action`：`noise` ⇒ `keep`；其余 ⇒ `overwrite`。

**生产者**：`script/build/build_voice_conflict_map.py`（`--orig-dir` 或环境变量 `IFMH_ORIG_DIR`；`--ffmpeg` 可显式给路径，缺省自动探测 `FFMPEG` 环境变量 / `PATH` / `D:\ffmpeg\bin\ffmpeg.exe`，全无则退化容器级判据）。**消费方**：`script/build/build_restore_plan.py`（`action=overwrite` 子集**逐名**进资源分派的 `overwrite`，**不以「被还原内容引用」为门槛**，并以「语音覆盖名单数 ＝ 判定表 overwrite 数」为闸）、`script/build/build_patch.py`（整名替换同名成员，名单数须等于替换数）。判据与连带规则见 [resource-naming.md](../doc/resource-naming.md) §3。

## resource/restore_plan.json —— 插入与改档计划

**表结构**

| 字段 | 类型 | 含义 / 取值 |
|---|---|---|
| `A1` | dict | 整脚本还原：`{脚本名: {kind: 'whole', slots: int, texts, names, resources}}`，`texts` 与 `fan_cn/{SCRIPT}.json` 同源，`names` 是**真新增资源**的号段改名映射（同名冲突走覆盖 ⇒ 为空），`resources` 按资源类列名字 |
| `hosts` | dict | 逐宿主脚本 `{kind, plan, slot_texts, resources, n_drops, n_insert_rows}`；`kind` ∈ `host`（有改动）/ `skip`（只记 `kind`） |
| `hosts[].plan` | dict | `drops`(list[int]，被删槽位)、`inserts`(list[[锚槽, 原版起, 原版止]])、`external`(dict，插入块外跳转的改基目标)、`names`(dict，真新增资源的号段改名映射) |
| `hosts[].slot_texts` | list[str] | 最终槽位序的逐槽文本：保留格取官方 `.lng`，插入格取 `fan_cn/` |
| `hosts[].resources` | dict | 还原区间引用到的资源名，按 `png` / `pna` / `voice` / `se` / `bgm` 分类 |
| `jumps` | list | 入口尾跳改回原版的记录：`[宿主脚本, Steam 原目标, 恢复后的原版目标]` |
| `resources` | dict | 资源分派：`copy`(list[{kind, archive, orig}]，Steam 缺 ⇒ 补入并继承原名)、`overwrite`(list[{kind, archive, name, orig_name}]，整名覆盖：Steam 成员名与表位置不变、内容取 `orig_name` 的原版字节。**两路来源**——图像取自判定表 `censor_map.json` 的 `action=overwrite` 子集、语音取自判定表 `voice_conflict_map.json` 的 `action=overwrite` 子集，两表都**逐名**入表、不以被引用为门槛)、`have`(int，Steam 已存在且内容等同原版、或判为噪声 ⇒ 不动的数量)。**没有 `rename` 分类**（同名冲突不改名） |
| `reuse_rewrites` | list | 顶包调用点改写：`[{script, offset, slot, from, to}]`。`offset` 是**解码流内名字字节的绝对偏移**，`to` 与 `from` **等长**（在重建前的 Steam 解码流上做 NUL 定界精确替换，长度不变 ⇒ 不影响任何偏移）。来自判定表 `class=reuse` 成员的 `surviving_sites` 中 `decision='rewrite'` 的点；`to` 的资源分派（Steam 缺则补入）同步进 `resources` |
| `gates` | dict | `{'slots_<脚本名>': int}`，各脚本最终槽数，出包逐宿主核对 |

**生产者**：`script/build/build_restore_plan.py`（输入为 `adjudication/`、`carrier_map.json`、`rename_map.json`、`censor_map.json`、`fan_cn/` 与官方 zh-CN `.lng`）。**消费方**：`script/build/build_patch.py`（按 `hosts` 的槽位序写盘、按 `resources` 的 `copy` 补资源、按 `overwrite` **整名替换同名成员**、按 `reuse_rewrites` 改写顶包调用点，`have` 不写盘）。插入块写盘的资源名**照抄原版脚本里的名字**（覆盖不改名 ⇒ 原名即原版画面）；`plan.names` 的映射只服务**真新增资源**的号段改名（当前恒空），同名冲突不得经它改写。路线与门禁语义见 [restoration-route.md](../doc/restoration-route.md)。

## resource/achievement_map.json —— 成就基线

**表结构**

| 字段 | 类型 | 含义 / 取值 |
|---|---|---|
| `_source` | dict | `appid`(int)、`schema`(str，成就 schema 文件的取用口径)、`engine`(str)、`note`(str，编号规则) |
| `achievements[]` | list | 成就条目：`idx`(int，Steam 枚举序)、`api`(str)、`name`(str)、`desc`(str) |
| `trigger_sites[]` | list | `0xF0` 触发点：`script`(str，含 `.ws2` 后缀)、`offset`(str，十六进制串)、`idx`(int) |

`idx` 以 0 为基，越界值在引擎侧是空操作，因此该表是还原插入的只读约束：新增文本不得挪动既有 `F0` 的编号。**生产者**：人工登记。**消费方**：文档与人工核对（构建脚本不读取）。详见 [achievement-mechanics.md](../doc/achievement-mechanics.md)。
