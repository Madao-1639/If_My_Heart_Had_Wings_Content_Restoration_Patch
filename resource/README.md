# resource/ 数据索引

本目录是补丁的数据层：文本层底稿、中文文本产物、还原判定台账、施工计划。目录条目写**文件结构**，单表条目写**表结构**，并标出生产者与消费方；判读口径、工序与验收读数一律见 `doc/`，本文件不重复。

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

`zh/` 只为对白行建条目，因此它的逐脚本 `total` 比 `fan_cn/` 少掉的正是该脚本的 ctrl/menu/flag 行；条目数以 `doc/script-text-extraction.md` §6.4 的 count_parity 口径为准。

**生产者**：按条目导出的底稿，入库作对照存证。**消费方**：`tool/v5lib.py`（原版行文本，用于逐块判读与引证核验）、`script/build_fan_translations.py` 与 `script/acceptance.py`（读 `zh/` 的 `total` 作条目数诊断对照）。

### pairing.jsonl

**表结构**（一行 = 一条原版文本行）

| 字段 | 类型 | 含义 / 取值 |
|---|---|---|
| `script` | str | 脚本名 |
| `kind` | str | 行类，`dlg` / `ctrl` / `name` / `menu` / `flag`（形态与建槽规则见 [script-text-extraction.md](../doc/script-text-extraction.md) §5） |
| `idx` | int \| null | 槽位号：`dlg`/`ctrl` 取脚本内 idx，`menu`/`flag` 取选项或 `FLAG_CHECK` 的 id，`name` 行为 null |
| `off` | int | 该行在解码流中的字节偏移 |
| `seq` | int | 按 `off` 排序后的脚本内行序（0 起） |
| `jp` | str | 原文（cp932 解码） |
| `cn` | str | 对齐到的译文；`src` 为 `need-translate` 的行是空串，由构建阶段就地补译，不落原文 |
| `src` | str | 配对来源：`positional`（位置对齐）/ `crc-tail`（按 CRC32 在尾部残量里认领）/ `ctrl`（清屏行）/ `need-translate`（无译文） |
| `crc` | int | 引擎口径的查表键（`crc32_signed`，有符号） |

**生产者**：`script/align_corpus.py`。**消费方**：`script/build_fan_translations.py`（出包）与只读复检脚本（`script/count_parity.py`、`script/extraction_accuracy.py`、`script/nohan_scan.py` 等）。

### review_fixes.jsonl

**表结构**（一行 = 一个被语境层改写的槽位）

| 字段 | 类型 | 含义 / 取值 |
|---|---|---|
| `script` | str | 脚本名 |
| `idx` | int | 槽位号 |
| `kind` | str | 行类，与 `pairing.jsonl` 同行类口径 |
| `from` | list[str] | 来源层名。只记**最终生效层**：同一槽位被后层改写时不保留前层名，所以各批改动的落地计数会大于该层在表内的现存槽数 |
| `cn` | str | 终值文本 |

**生产者**：`script/merge_fixes.py`（全表按规则重建；新增改动按槽位增量并入）。**消费方**：`script/build_fan_translations.py`（语境层套用与出包门禁）、只读复检脚本。层名清单与合成规则见 [script-text-extraction.md](../doc/script-text-extraction.md) §7.2。

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

**生产者**：`script/build_fan_translations.py`（脚本 JSON 与 `manifest.json`）、`script/build_nametable.py`（`NameTable.json`）。**消费方**：`tool/fancn.py`（装载与复检的统一读取口）、`script/acceptance.py` 等只读复检、`script/build_restore_plan.py`（插入行取中文文本）、`script/build_l4.py` 与 `script/convert_sl_ws2.py`（`SL_*` 的装载形态与译名合并）。

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

**生产者**：`script/build_carrier_map.py`。**消费方**：`tool/v5lib.py`（唯一直接读取口，判读批次生成与校验器都经它）。

## resource/adjudication/ —— 判读台账

**文件结构**：逐脚本一份 `{SCRIPT}.jsonl`，另有 `rereview_{线名}.jsonl` 存复判件。主表一行 = 一个判读块，字段：

| 字段 | 类型 | 含义 / 取值 |
|---|---|---|
| `script` | str | 脚本名 |
| `block_orig` / `block_steam` | list[int] | 本块覆盖的原版行区间／Steam 槽位区间，闭区间 `[起, 止]`；起大于止表示该侧无行 |
| `cells[]` | list | 逐槽判定：`slot`(int)、`action`(str ∈ `keep` / `drop` / `rebind`)、`form`(str，处置名称)、`quote`(str，该槽文本的逐字引文)；`rebind` 另带 `bind_orig_row`(int，改绑到的原版行)，部分再带 `orig_quote`(str，该行原文引证) |
| `inserts[]` | list | 整段插回：`after_slot`(int，插在哪一槽之后)、`orig_rows`(list[int]，闭区间)、`form`(str)、`quote`(str) |
| `orig_waived` | list[list[int]] | 判定不还原的原版行闭区间 |
| `verdict` | str | 一句话裁定（自由文本，不是枚举） |
| `note` | str | 判据说明 |

复判件字段为 `script` / `block_orig` / `block_steam` / `scene`(str，同拍／复述等场景类别) / `current`(str，原裁定) / `action`(str ∈ `stands` 等) / `reason`(str)，只作判读证据，消费方按 `rereview` 前缀跳过。

**生产者**：人工逐块判读的交付，经 `script/check_adjudication.py` 校验（块与承载图相符、槽位与原版行全覆盖且每处恰一次、引文逐字命中）后落地。**消费方**：`script/build_restore_plan.py`（`cells` 的 `drop` 与 `inserts` 合成删槽／插入行集）、`script/build_rename_map.py`（`inserts` ∪ `rebind` 的原版行号界定资源引用面）。裁定标准见 [restoration-targets.md](../doc/restoration-targets.md)「判定标准：差分形态与采用口径」。

## resource/rename_map.json —— 改名表

**表结构**：按资源类分表，每表是条目列表。

| 字段 | 类型 | 含义 |
|---|---|---|
| `est` / `voice` / `sprite` / `mos` | list | 冲突且被还原内容引用、需改名的资源；条目含 `orig`（原名）、`patch`（补丁内名）、`source_archive`（归属归档），立绘条目另带 `role` |
| `unparseable` | list | 解析不出补丁名或该类号段已用尽、因此未能自动改名的项；条目含 `name`、`archive`，另带 `referenced_as`（引用形态）或 `reason`（如号段耗尽） |
| `unused_conflicts` | list | 同名冲突但未被还原内容引用，不改名；条目含 `archive`、`name` |
| `meta` | dict | `conflict_names`(int)、`referenced_names`(int)、`restored_scripts`(list[str])、`reference_scan`(str，引用扫描的指令口径)、`rule`(str，改名规则)、`segment`(str，号段分配)、`spec`(str，规范文档) |

**生产者**：`script/build_rename_map.py`。**消费方**：`script/build_restore_plan.py`（还原区间内引用的改名映射与资源三分类）。号段与红线见 [resource-naming.md](../doc/resource-naming.md)。

## resource/restore_plan.json —— 插入与改档计划

**表结构**

| 字段 | 类型 | 含义 / 取值 |
|---|---|---|
| `A1` | dict | 整脚本还原：`{脚本名: {kind: 'whole', slots: int, texts, names, resources}}`，`texts` 与 `fan_cn/{SCRIPT}.json` 同源，`names` 是引用到的改名映射，`resources` 按资源类列名字 |
| `hosts` | dict | 逐宿主脚本 `{kind, plan, slot_texts, resources, n_drops, n_insert_rows}`；`kind` ∈ `host`（有改动）/ `skip`（只记 `kind`） |
| `hosts[].plan` | dict | `drops`(list[int]，被删槽位)、`inserts`(list[[锚槽, 原版起, 原版止]])、`external`(dict，插入块外跳转的改基目标)、`names`(dict，引用到的改名映射) |
| `hosts[].slot_texts` | list[str] | 最终槽位序的逐槽文本：保留格取官方 `.lng`，插入格取 `fan_cn/` |
| `hosts[].resources` | dict | 还原区间引用到的资源名，按 `png` / `pna` / `voice` / `se` / `bgm` 分类 |
| `jumps` | list | 入口尾跳改回原版的记录：`[宿主脚本, Steam 原目标, 恢复后的原版目标]` |
| `resources` | dict | 资源三分类：`copy`(list[{kind, archive, orig}])、`rename`(list[{kind, archive, orig, patch}])、`have`(int，Steam 已存在的数量) |
| `gates` | dict | `{'slots_<脚本名>': int}`，各脚本最终槽数，出包逐宿主核对 |

**生产者**：`script/build_restore_plan.py`（输入为 `adjudication/`、`carrier_map.json`、`rename_map.json`、`fan_cn/` 与官方 zh-CN `.lng`）。**消费方**：`script/build_patch.py`（按 `hosts` 的槽位序写盘、按 `resources` 的 `copy`／`rename` 补资源与改名，`have` 不写盘）。路线与门禁语义见 [restoration-route.md](../doc/restoration-route.md)。

## resource/achievement_map.json —— 成就基线

**表结构**

| 字段 | 类型 | 含义 / 取值 |
|---|---|---|
| `_source` | dict | `appid`(int)、`schema`(str，成就 schema 文件的取用口径)、`engine`(str)、`note`(str，编号规则) |
| `achievements[]` | list | 成就条目：`idx`(int，Steam 枚举序)、`api`(str)、`name`(str)、`desc`(str) |
| `trigger_sites[]` | list | `0xF0` 触发点：`script`(str，含 `.ws2` 后缀)、`offset`(str，十六进制串)、`idx`(int) |

`idx` 以 0 为基，越界值在引擎侧是空操作，因此该表是还原插入的只读约束：新增文本不得挪动既有 `F0` 的编号。**生产者**：人工登记。**消费方**：文档与人工核对（构建脚本不读取）。详见 [achievement-mechanics.md](../doc/achievement-mechanics.md)。
