# 引擎机制

本文档记录游戏引擎在运行时表现出的行为规律，区别于 [file-formats.md](file-formats.md) 记录的静态文件格式。可执行文件 `AdvHD.exe`/`AdvHD.dll` 存在于原版发行版目录中（见 [restoration-targets.md](restoration-targets.md)），必要时可用于运行时验证或静态逆向。

> ⚠️ **两个引擎二进制不等价**：**原版** `AdvHD.exe`（2013）未加壳、可完整静态分析，但**不含成就系统**；**Steam 版** `AdvHD.exe`（VAdvHD 1.72c `Release - Steam`）含成就系统，发行版被 DRM 加壳，**已脱壳**（`AdvHD.exe.unpacked.exe`）后可完整静态分析。
>
> **本文件只写引擎自身的行为规律**：槽位白名单、`layer_id` 越界、裸目录覆盖、`+` 系列覆盖归档、归档路由函数、缺图容错、成就触发点契约、画廊取图链路。
> 文件格式与字节布局见 [file-formats.md](file-formats.md)；成就完整机制见 [achievement-mechanics.md](achievement-mechanics.md)；后日谈机制见 [afterstory-mechanics.md](afterstory-mechanics.md)；两版差异与本补丁处置方针见 [restoration-targets.md](restoration-targets.md)／[restoration-route.md](restoration-route.md)。

## 状态图例

同 file-formats.md：✅ 已确认 / ⚠️ 部分确认 / ❓ 未知

## 资源槽位命名 ✅

- **槽位键白名单**即下节 `LAYER_ORDER.ws2` 的 19 键（`ev`；`bg01-02`；`st01-12`；`movie`；`text01-03`），脚本里实际出现的有 `st01`、`bg01` 等。
- 未知项：**是否存在按槽位的资源名长度限制**尚未验证。

**方法**：新增资源若在某槽位不被识别，优先用 A/B 测试（换成等长名字）定性问题，而不是纯静态逆向猜测。

## LAYER_ORDER 与 `layer_id` ✅ 已逐字节复核

同一引擎（AdvHD）的 CROSS†CHANNEL 项目结论对本项目**同样成立**（本项目已逐字节复核确认）。字节布局与 19 键清单见 [file-formats.md](file-formats.md)，本节只记引擎行为：

- **`LAYER_ORDER.ws2` 是「引擎已知槽位键」的白名单，不是布局表**（不含位置/坐标）。
- **槽位键由引擎内部硬编码**（Lua 绑定注册表）；`LAYER_ORDER` 只登记引擎**已经认识**的键 ⇒ **不能用它新增槽位**（C+C 侧 A/B 实测：加引擎不认识的新键永远注册不上）。
- **`layer_id` 是纯位置量**（公式与层序见 [pna-resources.md](pna-resources.md)），取值**依赖对应 PNA 的图层数**；请求 `layer_id ≥ layer_count` 会使**引擎崩溃**（C+C/ASF 侧实测 0x39；本项目待验证）。

⇒ **引擎后果**：脚本给的 `layer_id` 只对**当时那份 PNA 的图层数**成立。图层数不同的 PNA 不能被同一段脚本驱动。

## 资源缺失时的运行时行为 ⚠️ 部分确认

- **脚本层取图**（`openCgBrowser` / `LoadCg` / `LoadMove`）：取不到**不抛错、不崩**，返回失败值由 Lua 判断，由脚本自己打印 `ファイルが無かった`。实机证据见 §CG 鉴赏「一、按名字取图，缺图不报错」。
- **引擎层是否另有回退或占位**：未验证（未构造「有 flag、无图」以外的缺失形态，例如 PNA 图层数不足、通道引用越界）。

## `.MOS` 马赛克变体的选用机制 ⚠️ 身份已确认，触发条件待调查

已在 [file-formats.md](file-formats.md) 中确认 `.MOS` 是与部分立绘同名的马赛克遮罩变体文件（本身也是合法 PNG，但分辨率/文件大小明显更小）。已确认脚本内容中不包含对 `.MOS` 扩展名的直接引用，说明选用逻辑在引擎内部而非脚本层。需要通过运行时观察（例如切换游戏内的"隐藏敏感画面"设置项，若存在）或对 `AdvHD.exe` 做针对性逆向来确认触发条件。

## 成就触发点：引擎侧的契约边界 ✅

**引擎只做一件事**：按 `0xF0 <idx>` 的 `idx` 查运行时成就表 → 调 `SetAchievement` + `StoreStats`。成就的定义、API 名、图标、解锁状态全在 **Steam + 开发者**侧，引擎与脚本都不参与判定。

⇒ **脚本层唯一的成就接口是「触发点」**，共两类指令：

| 指令 | 语义 |
|---|---|
| `0xF0 <u8 idx>` | 直接触发第 `idx` 项成就（0 基枚举序） |
| `0x04 "CG_ACHIEVEMENT" 00` | 转交成就脚本，按其内部计数发收集类成就 |

成就触发点本身是**脚本字节**，不是引擎机制；其结构、保留纪律与验收判据分别见 [file-formats.md](file-formats.md)、[restoration-route.md](restoration-route.md) §2、[acceptance-criteria.md](acceptance-criteria.md)。完整成就机制（20 项映射、引擎 handler、Steam 侧构建）见 [achievement-mechanics.md](achievement-mechanics.md)。

### 引擎身份 ✅

- **VAdvHD 1.72c，`Release - Steam` 构建**；`ISteamUserStats` **v011**；引擎内直接使用 Valve Steamworks SDK 官方样例类 `CStatsAndAchievements`。`Script.arc` 全部 Lua **无**成就相关代码 ⇒ 成就完全由引擎 + 脚本触发点两方构成。
- 原版 `AdvHD.exe`（2013）**不含成就系统**（`Steam`／`ACHIEVEMENT`／`steam_api` 字符串计数均为 0），不能作为替代样本。
- Steam 版发行二进制被 Steam DRM 加壳，**已脱壳**（`AdvHD.exe.unpacked.exe`），成就的引擎侧实现已完整静态闭合。

## 后日谈（After Story）入口 ⚠️ 非引擎内建

**入口不是引擎内建概念**：它是普通的脚本层派发（标题菜单按钮 → Lua 选择界面 → `NextFile`），没有引擎侧的专用支持。因此引擎文档不再展开，机制与改动点全部见 [afterstory-mechanics.md](afterstory-mechanics.md)。

## 磁盘裸 `RIO/` 目录：引擎读取语义 ✅ 已确认

原版发行目录下有磁盘裸目录 `RIO/`（11 个 `.ws2`）。**引擎会读取裸文件并覆盖归档内的同名成员**——这是本书唯一与「裸目录」相关的引擎结论。

**依据（三条独立佐证）**：

1. 官方预约特典「スウィートラブパッチ」**只以裸 `RIO/` 形式发行**（`start.ws2` + 4 个 `SL_*.ws2`）；`Rio.arc` 内既无 `SL_*` 也未置 flag 1000。若引擎不读裸目录，该官方特典将完全无效 ⇒ 必然读取。
2. 裸 `RIO/start.ws2` 与归档内同名的实质差异正是 `SetFlag 1000`（裸 **1** / 归档 **0**），而 flag 1000 是标题菜单 `PatchFlag = GetFlag(1000)` 的来源。
3. **目录前缀资源根先例**：Steam 版官方中文以 `zh-CN/Rio.arc` 的目录前缀形式覆盖归档。

**判据**：字符串常量扫描不足以定论引擎行为——它只覆盖**字符串常量**，不覆盖运行时拼接的路径。

### 目录构成、来源与对位基线

裸 `RIO/` 不是构建残留，而是**两个官方补丁的散装覆盖层**（同级 `请读我.txt` 明载「已打官方修正补丁 v1.02」「已打官方予約特典 スウィートラブパッチ」）：特典贡献 `start.ws2` + 4 个 `SL_*.ws2`；v1.02 贡献 `CO1_001/002/003/015`、`HUT_004/005`。

⇒ **对位基线**：这 6 个文件在 Steam 侧的对位对象应是**裸 `RIO/`（v1.02）版**，而非 `Rio.arc` 内的旧版。逐文件差异明细与 L5 处置见 [restoration-targets.md](restoration-targets.md)；`HUT_004` 删行带来的语料行号平移见 [script-text-extraction.md](script-text-extraction.md)。

### `+` 系列覆盖归档

原版另有 `Voice+.arc`／`Chip+.arc` 两个「`+` 后缀」归档，成员与主线归档**同名但内容不同**（= 覆盖新版），由 `ArcFileName.lua` 的**无条件路由分支**派发（排在 `flag 126` 分支之前，先行命中），见下节。

**引擎侧结论**：`+` 归档只是普通的第二份归档，引擎不认识「`+`」这个后缀的语义——路由完全由 Lua 决定。它们是 **v1.02 修正补丁的载体**（成员时间戳与原版裸 `RIO/` 的 v1.02 文件同批），而**实测 Steam 基线已内含其修正内容** ⇒ 两条 `+` 分支都不在还原范围内。

**残留风险（未定项）**：裸目录覆盖的**粒度**（整档 vs 单体 `.ws2`）尚未实机 A/B 验证。

## 归档路由函数（`ArcFileName.lua`）✅

两个 Lua 全局函数，由引擎／脚本在取资源时调用，**返回值 = 该资源所在归档名**：`getGraphicsArcFileName`（立绘／CG／UI 图）与 `getSoundArcFileName`（语音／BGM／SE）。原版在 `LegacyGame.lua` `main.41`／`main.42`；Steam 搬到 Steam 独有的 `ArcFileName.lua`（`LegacyGame.inc` 末行 `include "ArcFileName"`）。

**两个参数用途不同，必须区分**：

| 参数 | 含义 | 用途 |
|---|---|---|
| **第 1 个**（`R0`） | 引擎构造的**资源标识**，含类别子串（`char`／`bgv`／`bgm`／`age`…） | sound 的全部 `find` 判定 |
| **第 2 个**（`R1`） | **文件名**（如 `AGE_1309.ogg`） | sound 的 3 条特例 `sub(R1,1,8)`；graphics 的全部判定 |

**文件名本身不含 `char`/`bgv`/`bgm`** —— `PVOICE.arc` 的成员名是 `AGE_10001.ogg`、`KOT_0387.ogg` 这类 ⇒ sound 的判定**不以文件名为输入**，命中的是引擎传入的类别标识。

```
getSoundArcFileName(R0, R1)                    # R0 = 类别标识；R1 = 文件名
  sub(R1,1,8).lower() ∈ {age_1309, kot_0387, kot_3837}  → Voice+.arc   # 特例，先行
  if GetFlag(126) == 1:                                  # ★ 后日谈分支
      find(R0,"char") → PVoice.arc
      find(R0,"bgv")  → PVoice.arc
      find(R0,"bgm")  → PBgm.arc
  find(R0,"char")        → Voice.arc                     # 常规分支
  find(R0,"bgv")         → Voice.arc
  find(R0,"bgm")         → Bgm.arc
  find(R0,"systemvoice") → SysVoice.arc
  默认                    → Se.arc

getGraphicsArcFileName(slot, R1)               # 判定全用 R1（文件名）
  sub(R1,1,9).lower() ∈ {sys_arrow, sys_configp7, sys_dialog, sys_log} → Chip+.arc
  sub(R1,1,4).lower() == "sys_"    → SysGraphic.arc
  if GetFlag(126) == 1:                                  # ★ 后日谈分支
      sub(R1,1,3).lower() ∈ {age, ama, hut, kot} → PChip.arc
  sub(R1,1,5) == "efmsk" → Graphic.arc                   # 常规分支
  sub(R1,1,2) == "bg" / sub(R1,1,3) == "sky" → Chip1.arc ；"age" → Chip2.arc ；"ama" → Chip6.arc
                "com"      → Chip2.arc ；"hut" → Chip3.arc ；"kot" → Chip5.arc
  sub(R1,1,4) == "sdev"  → Chip2.arc
  sub(R1,1,2) == "an" / "ef" → Chip4.arc ；sub(R1,1,3) == "est" → Chip4.arc ；"im" → Chip4.arc
  默认                     → Graphic.arc
```

**`voice`／`bgm`／`se` 的分流不是三个函数，而是同一个 `getSoundArcFileName` 内部的 `find` 子串链**（原版 `main.42` = 152 条指令）。要点：

- `char` 与 `bgv` **都返回 `Voice.arc`**（两个子串 → 同一归档）；
- **`se` 没有任何正面判定** —— 它是链尾的**兜底**（pc149 `LOADK "Se.arc"` → pc150 `RETURN`），语义是「不是 char/bgv/bgm/systemvoice 的一律算 SE」；
- **优先级**：3 条 `Voice+` 特例（用 **R1 文件名**、`sub(R1,1,8)`、**无条件、不看 flag 126**）→ `flag 126` 分支 → 常规链 → `Se.arc` 兜底；
- `flag 126` 分支内三个子串都不匹配时**不是返回，而是 fall through 到常规链**（pc50 的 `JMP +42` 只在 flag≠1 时跳）。

⇒ **`PSE.arc` 在 Lua 里没有任何分支可达**：`flag 126` 分支只处理 `char`/`bgv`/`bgm`，其余无条件返回 `Se.arc` ⇒ 它若被加载只能是引擎侧的挂载行为（未定项，见 [afterstory-mechanics.md](afterstory-mechanics.md) §9.4）。

**Steam 版删掉了 `flag 126` 分支、`Chip+`／`Voice+` 特例与全部 `P*` 归档**：

- `getSoundArcFileName`：`systemvoice`→`SysVoice.arc`／`char`·`bgv`→`Voice.arc`／`bgm`→`Bgm.arc`／默认→`Se.arc`（无 3 条文件名特例）；
- `getGraphicsArcFileName`：按名字前缀 → `sys_`→`SysGraphic.arc`、`efmsk`→`Graphic.arc`、`bg`·`sky`→`Chip1`、`age`·`com`·`sdev`→`Chip2`、`hut`→`Chip3`、`an`·`ef`·`est`·`im`→`Chip4`、`kot`→`Chip5`、`ama`→`Chip6`、默认→`Graphic.arc`（无 `sys_arrow`／`sys_configp7`／`sys_dialog`／`sys_log` 特例）；
- `getRioArcFileName`→`Rio.arc`；`getModelArcFileName`→`Model1.arc`；
- ⚠️ Steam `getSoundArcFileName`（`main.3`，86 条）的 **pc0–26 是死代码**：`NEWTABLE` 建空表 + `pairs({})`，循环体（按语言拼 `SysVoice` 前缀做 `find`）**永不执行** ⇒ 真正的判定链**从 pc27 开始**。

而后日谈的**数据端在 Steam 已完整**（`mainmenu.ws2`／`REPLAY_EXE.ws2` 跳 `SL_*` 前置 `flag 126 = 1`、`SL_*` 尾部置 0 逐字节在位）⇒ 只差路由端这一个分支，改动点与插入位置见 [restoration-route.md](restoration-route.md) §4.1。

## CG 鉴赏（Gallery / `CgBrowser`）：引擎侧行为 ✅

画廊在**引擎层几乎不参与**：条目表、页签、解锁判定全在脚本层（数据表 `CG_PAGE*.ws2` + `menu_gallery.lua`）。机制归属与完整派发链见 [afterstory-mechanics.md](afterstory-mechanics.md)（与回想共用同一套 Lua 菜单框架），数据表字节布局见 [file-formats.md](file-formats.md)。

引擎只有两条相关行为：

### 一、按名字取图，缺图不报错 ⚠️ 无保护

引擎按脚本给的**图名字符串**去归档取图；取不到时**不抛错、不崩溃、不回退占位**，只把失败值返回给 Lua。画廊侧据此打印 `ファイルが無かった`（`menu_gallery.lua` 的 `LoadCg()` 失败分支）。

⇒ **引擎层没有「缺图保护」**：表里任何一条指向不存在的图的记录，都是「一旦被点亮就报错」的潜伏缺陷——点亮条件（解锁旗标）与取图是两条独立路径，中间没有一致性校验。

该字符串在引擎二进制里**不存在** ⇒ 只由脚本产生，不是引擎错误码；日志里显示为乱码是输出端编码错配，不改变来源判定。

### 二、索引表本身不做校验

引擎读的是脚本给出的名字，**不校验表内记录与自己的一致性**。因此「表指向空图」不会被加载期发现，只在使用期暴露。

**本作实测规模**（`backup/` 与原版发行全 80 个文件字节级搜索）：`CG_PAGE` 的 881 条记录中 **283 条指向不存在的图**，全部为 Steam 表新增（原版表没有）。成因与影响面见 [restoration-targets.md](restoration-targets.md)；写盘侧因此产生的纪律见 [restoration-route.md](restoration-route.md) §6 V-14。

### 静态分析注意

`CG_PAGE10`／`CG_PAGE12` 含内嵌数据表，`ws2dis.disassemble()` 线性解析会**中途失步**（`ok` 标志只校验尾部长度，查不出失步）。权威失败清单与解析器鲁棒性缺口见 [file-formats.md](file-formats.md)。

## 待办

- [ ] 实机测试脚本层之外的资源缺失行为（PNA 图层数不足、通道引用越界等）
- [ ] 查明 `.MOS` 变体触发条件（游戏内设置项？还是硬编码判断？）
- [ ] 实测本项目 `layer_id ≥ layer_count` 的崩溃行为与错误码（C+C 侧为 0x39）
- [ ] 实测裸目录覆盖的**粒度**（整档 vs 单体 `.ws2`）
- [ ] 是否存在按槽位的资源名长度限制
