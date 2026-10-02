# 后日谈（After Story）机制

> 状态图例：✅ 已确认 ／ ⚠️ 部分确认（静态证据充分，未实机验证） ／ ❓ 未知
> 本文是 **L4 后日谈还原的开发依据**：机制全貌 + 既有实现位置 + 缺口与接口契约。
> 只写结论与依据（文件／偏移／指令号），不写探索过程。
> 基线：Steam = 仓库内 `backup/`（只读）；原版 = 原版发行版（**不在本仓库内**，下文一律以「原版」指代）。
> 范围分层见 [restoration-targets.md](restoration-targets.md)；构建路线见 [restoration-route.md](restoration-route.md)。

---

## 0. 机制总览

### 0.1 运行链

```
标题菜单 GameTitle
 └─ [PatchFlag 为真] 建 6 个按钮，含 sweet（id = 105，图形 Sys_title.pna 层 54/55/56）
     └─ [GetFlag(1001) ∧ (1002∧1005) ∧ 1003 ∧ 1004 全真] sweet:bt_SetActive(2.0) → 可点
         └─ 点击 → MenuButtonJob 写 var99 = 105
             └─ mainmenu.ws2  0x0145  var99 == 105 → Jump 818
                 └─ 0x0332  ExecuteFunction "openAfter"
                     └─ Lua 选择界面（SYS_After.pna / 子层 19 / 4 个海报按钮 id 1..4）
                         └─ 点击第 i 条 → MenuButtonJob 写 var99 = i
                             └─ mainmenu.ws2  var99 == 1..4
                                 └─ SetFlag 126 = 1 → NextFile "SL_KOT/AGE/AMA/HUT_001"
                                     └─ SL_* 尾部：SetFlag 126 = 0 → NextFile "TITLE"
```

回想入口（`REPLAY_EXE.ws2`）是另一条独立路径：按「页码 + 页内序号」选定条目 → **改写 `var110 = 18/19/20/21`** → `SetFlag 126 = 1` → `NextFile SL_*`；进入后 `SL_*` **头部**守卫 `flag[127] == 1 ∧ var[110] == 18..21` 成立 ⇒ 走到那条 `06` 直跳 H 场景入口（跳过整条路线的前段）；**尾部**同一对守卫成立 ⇒ 落到 `07 NextFile EVRET`，由 `EVRET`（4 条指令：`var110 >= 18` 则清 `flag126`，随后 `NextFile TITLE`）回收。正常路径（标题菜单 → 选择界面）**不置 `flag127`** ⇒ 头部守卫不成立、不执行那条 `06`，从头播整条路线；尾部守卫同样不成立 ⇒ 依「条件不成立才跳」的引擎语义跳到续场段（`0b flag[1068] = 1` → `timer01` → 下一场景 BG），不经过 `EVRET`。跳转携带者清单见 §9.2 G3。

⚠️ **Steam 版该入口结构性不存在**：派发脚本 `REPLAY_EXE.ws2` 与原版逐字节相同，但 `menu_gallery.lua` 的回想数据只到 `REPLAY_017`、`SceneMenu.PageMax = 2`，而 `SL_KOT` 分支要「第 2 页第 9 条」、其余三条要「第 3 页」（`var101 == 3`）⇒ 四条分支全部取不到（推理见 §5.3）。因此 `SL_*` 头部那条 `06` 在 Steam 侧是**不可达代码**，后日谈验收只需覆盖海报入口一条路径。

### 0.2 变量契约

| 变量 | 写入者 | 语义 |
|---|---|---|
| `99` | 菜单按钮 `MenuButtonJob` | 被选中按钮的 id（标题菜单 100–105；后日谈选择界面 1–4；取消 = 0 或 −1） |
| `100` | 鉴赏菜单 | CG 页码 |
| `101` | `menu_gallery.lua`（**唯一写入者**，`LegacyGame__lua_SetVariable(101, g_GalleryInfo.ScenePage)`） | **回想页码**（不是分类）。Steam 侧 `SceneMenu.PageMax = 2` ⇒ 只能取 1/2；`REPLAY_EXE.ws2` 的后日谈分支要求 `== 3` ⇒ 不可达（见 §5.3） |
| `110` | 先由 `menu_gallery.lua` 写「页内序号」（`SceneButtonJob`），再由 `REPLAY_EXE.ws2` 用 `0x09` 改写成「全局序号」（**浮点变量**） | 全局序号：主线回想 1–17，后日谈 **18 / 19 / 20 / 21**；`SL_*` 头部/尾部守卫与 `EVRET` 都读它 |
| `126` | 派发脚本（**布尔位图**，`0x0b` 写） | 后日谈归档路由开关：跳 `SL_*` 前置 1，`SL_*` 尾部或 `EVRET` 置 0 |
| `127` | `mainmenu.ws2 @0x308`（唯一写入点；离开时 `@0x182` 置 0） | **回想模式标记**（布尔位图）。与 `var110` 一起构成 `SL_*` 头部/尾部那对守卫的条件 ⇒ 决定走「直跳 H 场景 + 退场经 `EVRET`」还是「整条路线 + 续场段」 |
| `1000` | `start.ws2` | **Sweet Love 总开关**（原版裸 `RIO/start.ws2` = 1；arc 内 = 0） |
| `1001`–`1005` | 各线通关脚本 | 路线通关标记（见 §1.1） |

### 0.3 三处缺口（开发要补的全部内容）

| # | 缺口 | 位置 | 量级 |
|---|---|---|---|
| **G1** | 入口开关被硬置 `false` | `LegacyGame.lua` main.133 pc 90 | **2 字节** |
| **G2** | 选择界面函数改名后无人调用（孤儿） | `LegacyGame.lua` main.140 `openSceneSelect` | **1 处字符串常量字节改名** |
| **G3** | 4 个 `SL_*.ws2` 从 `Rio.arc` 删除 | `Rio.arc` | 4 脚本 + 引用资源 |

⇒ **除这三处外，机制链的脚本端在 Steam 版逐环节完整存在**（按钮代码、按钮图形、选择界面、脚本派发表、回想派发表、回主菜单尾跳）。⚠️ 回想入口的**数据端**除外：`menu_gallery.lua` 的条目表只到 17 条／2 页 ⇒ 该入口在 Steam 不可达，可达入口只有标题菜单 sweet（§5.3）。

### 0.4 原版发行形态

原版 Sweet Love 以**磁盘裸目录 `RIO/` 覆盖归档**的形式发行（11 个 `.ws2`）：

```
start.ws2          195 B   ← 总开关（SetFlag 1000 = 1）
SL_KOT_001.ws2  125452 B ┐
SL_AGE_001.ws2  131040 B ├ 4 条后日谈本体
SL_AMA_001.ws2  102980 B │
SL_HUT_001.ws2  134054 B ┘
CO1_001/002/003/015.ws2、HUT_004/005.ws2   ← H 场景出入口（属 L1–L3）
```

这些裸文件是**已解码明文**，可直接作为 L4 内容来源。对照 Steam `Rio.arc`：

| 文件 | Steam 侧 |
|---|---|
| `SL_KOT/AGE/AMA/HUT_001.ws2` | **完全缺失** |
| `CO1_001/002/003/015`、`HUT_004/005`、`start.ws2` | 存在但**内容不同**（Steam 版更大） |

---

## 1. 解锁机制 ✅

三段式：**写入端（通关标记）→ 读取端（判定并解灰）→ 辅助派生**。

### 1.1 写入端：路线通关标记（两版逐条一致）

扫描范围：两版 `Rio.arc` + `Script.arc` 全部 `.ws2`，匹配指令 `0x0b <u16 id> <u8 value>`。

| 脚本 | 指令 | 标记 | 女主 | 对应后日谈 |
|---|---|---|---|---|
| `KOT_009.ws2` | `SetFlag 1001 = 1` | 1001 | 小鳥 KOT | `SL_KOT_001` |
| `ASA_005.ws2` | `SetFlag 1002 = 1` | 1002 | アーシャ ASA | `SL_HUT_001`（与 YOR 共用） |
| `AGE_012.ws2` | `SetFlag 1003 = 1` | 1003 | あげは AGE | `SL_AGE_001` |
| `AMA_010.ws2` | `SetFlag 1004 = 1` | 1004 | 天音 AMA | `SL_AMA_001` |
| `YOR_008.ws2` | `SetFlag 1005 = 1` | 1005 | 依瑠 YOR | `SL_HUT_001`（与 ASA 共用） |
| `start.ws2` | `SetFlag 1000 = 0/1` | 1000 | — | **Sweet Love 总开关** |

两版命中集**逐条相同**（另有 1008 / 1009，与后日谈无关）。
⇒ **解锁数据在 Steam 版完整保留。**

### 1.2 读取端 A：选择界面逐条解锁

| 按钮 | 原版 `openAfter`（main.210，扁平序 #372） | Steam `openSceneSelect`（main.140，扁平序 #253） | 解锁条件 |
|---|---|---|---|
| 1 | `SC01`，id = 1 | `Scene1`，id = 1 | `GetFlag(1001) ~= 0` |
| 2 | `SC02`，id = 2 | `Scene2`，id = 2 | `GetFlag(1003) ~= 0` |
| 3 | `SC03`，id = 3 | `Scene3`，id = 3 | `GetFlag(1004) ~= 0` |
| 4 | `SC04`，id = 4 | `Scene4`，id = 4 | `GetFlag(1002) ~= 0 and GetFlag(1005) ~= 0` |

各条满足即 `MenuButtonData.<名字>:bt_SetActive(2.0)`（解除灰态）。
原版 main.210 pc 110–159；Steam main.140.2（`TrialInit`）pc 43–92。**逐条等价。**

第 4 条（HUT）需 **ASA 与 YOR 双线通关**，与 `SL_HUT_001` 的剧情定位一致。

### 1.3 读取端 B：标题入口总开关

| | 原版 main.196 `titleMenu` | Steam main.133.8 `TitleMenuInit` |
|---|---|---|
| 前置 | `MenuInf.PatchFlag` 为真 | `g_TrialFlag == 0` 且 `PatchFlag` 为真 |
| 判定 | `GetFlag(1001) ∧ (GetFlag(1002) ∧ GetFlag(1005)) ∧ GetFlag(1003) ∧ GetFlag(1004)` | 同（pc 362–392，`1002` 与 `1005` 先做 `and`） |
| 动作 | `MenuButtonData.sweet:bt_SetActive(2.0)` | 同（pc 393–397） |

两版语义等价。**入口点亮条件是 5 条线全部通关**（不是"通关一条"）；未全通关时按钮仍存在但为灰态、不可点。

### 1.4 `PatchFlag` 的来源（G1 的成因）

| 版本 | 代码 | 值 |
|---|---|---|
| 原版 | main.196 pc 22–25：`MenuInf.PatchFlag = GetFlag(1000)` | 由 `start.ws2` 决定 |
| Steam | main.133 pc 82–86：`MenuInf.PatchFlag = GetFlag(1005)`，**pc 90 随即 `= false`** | **恒 false** |

`start.ws2` 对 flag 1000 的赋值：

| 文件 | 值 |
|---|---|
| 原版 `Rio.arc:start.ws2` | **0** |
| 原版裸 `RIO/start.ws2`（195 B） | **1** ← 原版「Sweet Love 已安装」的开关 |
| Steam `Rio.arc:start.ws2`（126 B） | **0** |

⇒ Steam 侧是**双重关闭**：数据源写 0 + 代码硬置 `false`。G1 只需解开后者（见 §7.1）。

### 1.5 辅助派生

`FLAG_CHECK.ws2`（`Rio.arc`，两版**字节完全相同**，415 B）由路线标记派生辅助标记 120–124 与配置项 id 51（`0x0d 33 00 01 00 00 00 40` ＝ 配置 51 置 `3.0`）。

### 1.6 `bt_SetActive` 的定义位置 ✅

**在 `ui_button.lua`**（Steam 新增模块，`LegacyGame.inc` 已 include）：该模块 pc 92 `SETTABLE R15[K47('bt_SetActive')] := R16`，同处定义全部 `bt_*`（`bt_SetOnOffActive`／`bt_SetEnableSubLayer`／`bt_ResetActive`／`bt_SetColor`／`bt_PlayAnim`／`bt_MovableStart`…）。
原版这些方法内联在 `LegacyGame.lua` 内，Steam 抽出为独立模块。

⇒ Steam 侧可直接调用，**不是引擎绑定，无跨版本风险**。

---

## 2. 调用链与既有实现位置

| 环节 | 原版 `LegacyGame.lua` | Steam `LegacyGame.lua` | 状态 |
|---|---|---|---|
| 标题菜单主体 | main.196 `titleMenu`（扁平序 #304） | main.133 `GameTitle` | ✅ 既有 |
| 标题菜单初始化 | main.196 pc 0–… | main.133.8 `TitleMenuInit` | ✅ 既有 |
| 标题按钮子函数 | main.196.2 | main.133.3 | ✅ 既有 |
| 按钮类与 `bt_*` | 内联在 `LegacyGame.lua` | **`ui_button.lua`** | ✅ 既有 |
| 入口开关 | `PatchFlag = GetFlag(1000)` | `PatchFlag = GetFlag(1005)` 后**强制 `false`** | ⚠️ **G1** |
| 按钮图形 | `Sys_title.pna` 层 54/55/56 | 同（两版同结构，67 层） | ✅ 既有 |
| 选择界面 | main.210 `openAfter`（扁平序 #372） | **main.140 `openSceneSelect`（扁平序 #253）** | ⚠️ **G2**（改名 + 无调用点） |
| 选择界面图形 | `SYS_After.pna` | 同（两版同结构，20 层） | ✅ 既有 |
| 脚本派发 | `mainmenu.ws2` | `mainmenu.ws2`（已含 `openAfter` 与 4×`SL_*` 分支） | ✅ 既有 |
| 回想派发 | `REPLAY_EXE.ws2` | 与原版**字节完全相同**（837 B） | ✅ 既有 |
| 后日谈脚本 | 裸 `RIO/SL_*.ws2` | **缺失** | ⚠️ **G3** |
| 回主菜单 | `SL_*` 尾部 `NextFile "TITLE"` | 同（脚本本体） | ✅ 既有 |

---

## 3. 入口机制（标题菜单 sweet 按钮）✅

### 3.1 既有实现

`LegacyGame.lua` main.133（`GameTitle`）：

```
[ 82] GETGLOBAL R2 = cfunc
[ 83] GETTABLE  R2 = R2["LegacyGame__lua_GetFlag"]
[ 84] LOADK     R3 = K26 (1005.0)
[ 85] CALL      R2 = GetFlag(1005)
[ 86] SETTABLE  g_Menu.GameTitle.ptr["PatchFlag"] = R2
[ 87] GETGLOBAL R1 = g_Menu
[ 88] GETTABLE  R1 = R1["GameTitle"]
[ 89] GETTABLE  R1 = R1["ptr"]
[ 90] SETTABLE  R1["PatchFlag"] = K27 (bool false)      ← ★ G1
```

`LegacyGame.lua` main.133.8（`TitleMenuInit`）：

```
[185] GETTABLE R5 = self["PatchFlag"];  TEST;  JMP 0 -> 279
      → 真分支 [188]-[278]：6 键布局，含
        MenuAnimButtonSet("btnState2", …, "sweet", 54.0 / 55.0 / 56.0, id = 105.0)
[279]-[353] 假分支：5 键布局（无 sweet）
[356] GETGLOBAL R5 = g_TrialFlag;  EQ 0.0  → 为 0 则继续（解锁块执行）
[359] GETTABLE self["PatchFlag"];  TEST;  JMP 0 -> 398
      → 真分支 [362]-[397]：取 GetFlag(1001/1002/1003/1004/1005)，
        R6 = GetFlag(1002) and GetFlag(1005)，
        全部满足时 MenuButtonData["sweet"]:bt_SetActive(2.0)   （解除灰态）
[398]-[431] gallery / load 按钮解锁 + SetColor
```

常量表（main.133，共 46 项，实测类型）：

| 常量 | 类型 | 值 | 备注 |
|---|---|---|---|
| K26 | num | 1005.0 | 亦在 `[109] LOADK R6 := K26`（GetAllClearFlag 链）复用 |
| K27 | **bool** | **false** | `[90]` 与 `[143]` 引用 |
| K36 | **bool** | **true** | `[148]` 引用 |

`g_TrialFlag` 在 main.0 pc 141–142 初始化为 `0.0`，全工程再无写入 ⇒ 恒为 0 ⇒ 解锁块恒执行。

图形资源：`Sys_title.pna`（`SysGraphic.arc`）两版头结构相同——`PNAP`，`unknown=2960`，1280×720，**67 层**；层 54/55/56 即 sweet 按钮三态（Steam 版图形存在、未阉割）。

### 3.2 行为契约

| 条件 | 表现 |
|---|---|
| `PatchFlag` 真 + 5 线全通 | sweet 按钮**创建且可点** |
| `PatchFlag` 真 + 未全通 | sweet 按钮**创建但灰态不可点**（需求②） |
| `PatchFlag` 假（Steam 现状） | 6 键布局整体走假分支，**无 sweet 按钮** |
| 点击 sweet | `MenuButtonJob` 写 `var99 = 105` |

### 3.3 另一处独立开关（勿混）

`ui_language.lua` 的 `getJPatchFlag()`（`PatchFlag = false; return PatchFlag`，写的是**全局** `PatchFlag`）与标题菜单的 `GameTitle.ptr.PatchFlag` **字段**无关。它在 `LegacyGame.lua`／`menu_config.lua`／`menu_gallery.lua`／`ArcFileName.lua` 中被引用，属 L1–L3 的 H 内容开关范畴；与本项**互不干扰**，不能靠翻转 `getJPatchFlag` 顺带解决。

---

## 4. 选择界面机制 ⚠️（既有，需接线）

### 4.1 Steam `openSceneSelect`（main.140）与原版 `openAfter`（main.210）对照

| 项 | 原版 main.210 `openAfter` | Steam main.140 `openSceneSelect` |
|---|---|---|
| Menu 对象 | `g_AfterMenu = Menu:new("AfterMenu")` | `g_Menu.SceneSelect.ptr = Menu:new("SceneSelect")` |
| 子层基名 | `AfterBace` | `SceneSelect01` |
| PNA 文件 | `SYS_After.pna` | 同 |
| 子层号 | 19 | 19 |
| 按钮 API | `MenuButton:ButtonCreate` + `SetList` | `MenuButtonSet`（Steam 新版 API） |
| 按钮名 | `SC01`…`SC04` | `Scene1`…`Scene4` |
| 按钮 id | 1 / 2 / 3 / 4 | 1 / 2 / 3 / 4 |
| 按钮初始化子函数 | `startAfter`（main.210.2） | `TrialInit`（main.140.2） |
| 按钮事件名 | `LD` / `RU` | `LU` / `RU` |
| 解锁判定 | pc 110–159 | main.140.2 pc 43–92（逐条等价） |
| 收尾 | `NeedProcess(LUA_PROCESS_GAME_PAUSED, 0)`、`g_menuExecute = true`、`return true` | 同 |
| **调用点** | `mainmenu.ws2` 的 `ExecuteFunction "openAfter"` | **无（孤儿函数）** |

`mainmenu.ws2`（Steam，1179 B）仍保留 `ExecuteFunction "openAfter"` 与 4 个 `SL_*` 分支 ⇒ 一旦 sweet 可点，脚本会调用一个**在 Steam 未定义的全局** `openAfter`。这是 G2。

### 4.2 接线契约（G2）

> **✅ 契约（G2）**：把 `LegacyGame.lua` @`0x2a18` 的字符串常量项 `\x04 <len=16> "openSceneSelect"\0` 就地改为 `\x04 <len=10> "openAfter"\0`（长度前缀与含 NUL 的字节块一起改，15 字符 → 9 字符）。该串全库**唯一一处**（即全局注册名），Lua 字节码字符串自带长度前缀、跳转全为**相对偏移** ⇒ **改长度无需修正任何偏移**，也不需要 Lua 编译器。落地见 §9.2 G2。

**备选（仅在改名不可行时）**：在任一已被 `LegacyGame.inc` include 的模块（如 `ui_language.lua`，254 B）末尾追加**转发函数**：

```lua
function openAfter(...) return openSceneSelect(...) end
```

- **必须用 `function` 而非赋值**：`openAfter = openSceneSelect` 在模块加载时求值，而 `openSceneSelect` 由 `LegacyGame.lua` 注册，加载顺序不保证 ⇒ 会捕获 `nil`。转发函数在**调用时**解析全局，与加载顺序无关。
- 备选：新增模块 `menu_after.lua` + 在 `LegacyGame.inc` 追加 `include "menu_after"`（需确认引擎对新增 include 的容忍度）。
- **不改 `mainmenu.ws2` 字符串**：`openAfter`（9 字符）→ `openSceneSelect`（16 字符）长度不等，需重建脚本并修正全部跳转偏移，违背「就地插入」纪律。

### 4.3 事件与 id 契约 ✅

Steam `GameTitle.MenuButtonJob`（main.133.5）与 `SceneSelect.MenuButtonJob`（main.140.1）**同用 `LU` 事件**：

```
[ 2] EQ if R2 ~= 'LU' then pc++
...
[23] LOADK R5 := 99.0 ; [24] MOVE R6 := R1 ; [25] SetVariable(99, R1)   ← 按钮 id → 变量 99
[41] EQ if R1 == 105.0 ...                                               ← sweet 按钮
```

⇒ `SceneSelect` 的按钮同样写出 `var99 = id`（1..4），与 `mainmenu.ws2` 的 `var99 == 1..4` 分支对齐。

### 4.4 可用 API ✅

`menu_base.lua` 提供：`Menu:new`、`MenuInit`、`MenuButtonData`、`MenuButtonSet`、`MenuAnimButtonSet`、`MenuMoveButtonSet`、`MenuButtonInit`、`initSubLayer`、`setSubLayerParam`／`getSubLayerParam`、`MenuEffectStart/End/ToMenu`、`MenuMouseMove`、`MenuLButtonDown/Up`、`g_SysSEName`、`SystemSePlay` 等。
`bt_*` 方法定义在 `ui_button.lua`（§1.6）。

### 4.5 资源 ✅

`SYS_After.pna`（`SysGraphic.arc`）两版头结构相同：`PNAP`，`unknown=892`，1280×720，**20 层**。
层位：0 = 彩条遮罩，2–5 = 4 位女主海报，8–11 = 高亮态，14–17 = 灰态（需求②）。
按钮 SE：`SYS01.ogg`／`SYS03.ogg` 在**两版** `SE.arc` 中均存在。

### 4.6 未定项（§8-2）

`openSceneSelect` 在 Steam 属死代码，其子层基名 `SceneSelect01` 与 Steam `SYS_After.pna` 的实际匹配性、`MenuButtonSet` 参数表、取消路径过渡效果均需实机确认。

---

## 5. 派发机制 ✅

### 5.1 Steam `mainmenu.ws2`（`Rio.arc`，1179 B）完整派发表

```
0x0145  Condition id99 == 105 → Jump 818
0x0332  ExecuteFunction "openAfter"                    ← 调用 Lua 选择界面
0x0341  Condition id99 == 1 → ClearLayer / SetBackground bg01 WHITE.PNG
                              / StopMusic systembgm / SetFlag 126 = 1
                              → NextFile "SL_KOT_001"
0x0394  Condition id99 == 2 → … → NextFile "SL_AGE_001"
0x03e7  Condition id99 == 3 → … → NextFile "SL_AMA_001"
0x043a  Condition id99 == 4 → … → NextFile "SL_HUT_001"
0x048d  Jump 20                                        ← 无匹配时重入主菜单
0x0492  FileEnd
```

其余分支（供对照，非后日谈）：`99 == 100` → `CO1_001`（START）；`101`／`102` → 子菜单；`103` → 鉴赏；`104` → 退出；`99 == 1`（在 `0x0197` 段）→ `CG_PAGE01..12`；`99 == 2`（`0x02f8` 段）→ `REPLAY_EXE`。

### 5.2 原版 `mainmenu.ws2`（1099 B）—— 逐条对应 ✅

| 原版 | Steam |
|---|---|
| `0x0136 id99==105 → Jump 799` → `0x031f ExecuteFunction "openAfter"` | `0x0145 … → 0x0332` 同 |
| `0x032d id99==1 → SetFlag 126=1 → NextFile SL_KOT_001` | `0x0341` 同 |
| `0x0371 id99==2 → SL_AGE_001` | `0x0394` 同 |
| `0x03b5 id99==3 → SL_AMA_001` | `0x03e7` 同 |
| `0x03f9 id99==4 → SL_HUT_001` | `0x043a` 同 |
| 无 `0x84` | Steam 操作码 `0x84`，格式 `06 08 06 08 06 08 05 01 05 ff`（3×str + f32 + u8 + f32）；原版表该项为 NULL ⇒ 演出指令层差异，见 [engine-mechanics.md](engine-mechanics.md) |
| 跳 `SL_*` 前无 `StopMusic` | 多一条 `StopMusic systembgm` |

⚠️ **原版没有 `0x84` 转场标记**：原版引擎格式表中 `0x84` 为 NULL（`0x84` 是 Steam 新增操作码），实测原版 `mainmenu.ws2` 用原版表解析为 113 条指令、`0x84` 从不落在操作码位 ⇒ 原版脚本里出现的 `0x84` 字节只是操作数。

反汇编原版 WS2 的正确做法是**把 `tool/ws2dis.py` 的 `FORMATS` 换成原版引擎自带的格式表**（`AdvHD.exe` 文件偏移 `0x1212c0`，见 [file-formats.md](file-formats.md)）；按 Steam 表硬解会切错指令边界。`FORMATS` 是模块级字典，可逐项覆盖——`0x1c` 这类两版尾部长度不同的操作码必须覆盖，否则按字符串边界自动判定会多算 1 字节。

⇒ **脚本层无需任何改动**，唯一前提是 §4.2 的 `openAfter` 能返回并写入 `var99`。

### 5.3 回想派发（`REPLAY_EXE.ws2`）

两版**字节完全相同**（837 B）。全表（`var101` = 回想页码，`var110` = 页内序号，命中后改写为全局序号再 `NextFile`）：

```
var101 == 1（第 1 页）var110 1..9  → 全局 1..9  → KOT_003 KOT_003 KOT_006 KOT_009 AGE_005 AGE_007 AGE_010 AGE_010 AMA_004
var101 == 2（第 2 页）var110 1..8  → 全局 10..17 → AMA_006 AMA_007 AMA_010 ASA_002 ASA_004 YOR_003 YOR_005 YOR_007
                      var110 == 9  → 全局 18 → SetFlag 126 = 1 → NextFile "SL_KOT_001"
var101 == 3（第 3 页）var110 1..3  → 全局 19/20/21 → 各自 SetFlag 126 = 1 → NextFile "SL_AGE_001" / "SL_AMA_001" / "SL_HUT_001"
否则                                   → NextFile "TITLE"
```

⇒ ⚠️ **这条路径在 Steam 版结构性不存在**，`SL_*` 文件到位也不足以直达。派发脚本完整（四条后日谈分支原样保留），但**数据端被砍**：`menu_gallery.lua` 的回想条目表只到 `REPLAY_017`（对应 flag 1050–1066），缩略图 `ThXLineMax × ThYLineMax = 3×3 = 9`/页、`SceneMenu.PageMax = 2`；`var101` 由 `LegacyGame__lua_SetVariable(101, g_GalleryInfo.ScenePage)` 独家写入 ⇒ 取值只能 1/2。Steam 的 17 条 = 第 1 页 9 条 + 第 2 页 8 条 ⇒ 第 2 页第 9 条（`SL_KOT`）与整个第 3 页（`SL_AGE`/`SL_AMA`/`SL_HUT`）**都取不到**。原版能走通是因为原版回想条目为 21 条、需 3 页。⇒ 后日谈**唯一可达入口 = 标题菜单 sweet**；`SL_*` 头部那条 `06` 直跳在 Steam 侧为不可达代码（保留仅为与原版结构一致，见 §9.2）。

### 5.4 两版 WS2 编码不完全兼容

权威结论见 [file-formats.md](file-formats.md) §两版操作数格式表与原版脚本转换。要点：

- 两版引擎各自带 256 项操作数格式表；**Steam = 原版 + 若干操作码尾部追加常量操作数（`0x00` / f32 `0.0`）+ 新增操作码**，不存在原版有而 Steam 无的操作码 ⇒ 原版脚本总是可转换。
- SL 脚本用到的差异操作码仅 6 个：`0x11`（str 与 f32 间插 `0x00`）、`0x14`/`0x15`/`0x16`（尾插 `0x00`）、`0x1e`/`0x28`（尾插 f32 `0.0`）；其余操作码格式一致、操作数两版逐字节相同，原样复制。
- `0x1c` 两版都是**双 name**（第二个为空串），只差尾部 1 个 u8，且 SL 脚本不含 `0x1c`；`0x84` 在原版表中为 NULL（Steam 新增操作码），原版脚本里的 `0x84` 字节只是操作数 ⇒ 不存在「原版 `0x1c` 单 name」「原版转场标记 `0x84`」这两种形态。
- **转换实现**：`script/convert_sl_ws2.py` 把 4 个原版裸 `SL_*.ws2` 转为 Steam 编码（校验：Steam 表回读自洽、头部 `var127=1.0`/`var110=18..21` 与尾部 `SetFlag 126=0 → NextFile "TITLE"` 原样、无成就指令混入）。产物在 L4 构建层 `tmp/_l4/asset/RIO/`。
- ⚠️ **插入取值的依据 = Steam 自身 159 个成员中该字段的取值分布**（`0x11` 插值 1552/1552 为 `0x00`、`0x14` 43881/43886、`0x15` 87739/87739、`0x16` 7950/7950、`0x1e` 1149/1150、`0x28` 20947/20948 为 `0.0`；反例全部来自线性解析失步的 `CG_PAGE09` 系）。**两版同名的 `CO1_*`/`HUT_004` 配对脚本不可用于取值验证**：它们两版正文已分化（`CO1_001` 首指令原版 `0x16` vs Steam `0xf0`，`CO1_003/015`、`HUT_004` 在第 3–5 条即分叉），无法逐条对齐。交叉验证：同一批原版脚本用 Steam 表解析会在开头 `0xc2`–`0x406` 处撞到无格式操作码而失败，用原版表则完整解析（6234/6571/5156/5950 条）；还原产物反之 —— 只有 Steam 表能完整解析，且指令数与原版一致。

---

## 6. 返回机制（回主菜单）✅

4 个 `SL_*.ws2` 尾部结构一致：

```
…  0x0b 0x7e 0x00 0x00      (SetFlag 126 = 0，清除跳过标记)
   0x07 "TITLE" 0x00        (NextFile TITLE)
   0xff …                   (FileEnd)
```

文件尾字节（含 `TITLE` 偏移）：`SL_KOT_001` @0x1e9fd、`SL_AGE_001` @0x1ffd1、`SL_AMA_001` @0x19235、`SL_HUT_001` @0x20b97。

`mainmenu.ws2`／`REPLAY_EXE.ws2` 在跳 `SL_*` 之前均已 `SetFlag 126 = 1`。⇒ **回主菜单天然成立，无需改动。**

各 `SL_*.ws2` 头部 `Condition(mode=130, id=110, ==18/19/20/21)` 与 `REPLAY_EXE.ws2` 跳转前 `LayerConfig(id=110, 18/19/20/21)` 一一对应，链路自洽。

---

## 7. 开发依据

### 7.1 改动清单

| # | 目标 | 改动 | 量级 | 风险 |
|---|---|---|---|---|
| 1 | `Script.arc` → `LegacyGame.lua` | 成员偏移 **`0x234b0`** 处 4 字节 `49 c0 c6 8b` → `49 00 c9 8b`（main.133 pc 90 的 C 操作数 `K27(false)` → `K36(true)`） | **2 字节** | 低 |
| 2 | `Script.arc` → `ui_language.lua`（或任一已 include 模块） | 追加 `function openAfter(...) return openSceneSelect(...) end` | **1 行** | 低（⚠️ 依赖 §4.6） |
| 3 | `Rio.arc` | 新增 4 个 `SL_*.ws2`（原版裸 `RIO/SL_*.ws2` 回填，须按 Steam WS2 编码校验／转换） | 小 | 中（§5.4） |
| 4 | `mainmenu.ws2` / `REPLAY_EXE.ws2` / `start.ws2` / `ui_button.lua` / `menu_base.lua` | **无** | — | — |
| 5 | `SysGraphic.arc` / `PVOICE.arc` / `PCHIP.arc` / `PBGM.arc` / `PSE.arc` / `CHIP4.arc` | 回填 `SL_*` 引用资源 | 中 | 低（同名冲突按项目约定「只隔离改名、禁覆盖」处理） |

**备选方案（改动 1）**：pc 90 的 C 操作数改为寄存器 `R2`（`0x8bc6c049` → `0x8b808049`，同偏移 2 字节）⇒ `PatchFlag = GetFlag(1005)`，sweet 按钮仅在 YOR 通关后创建。与原版「补丁开关」语义不同，但最终可见结果（5 线全通才可点）一致。

**已废弃方案**：把 K26 由 `1005.0` 改为 `1000.0` —— **会破坏 pc 109**（`GetAllClearFlag = 1001∧1002∧1003∧1004∧GetFlag(K26)`，K26 变 1000 后因 flag 1000 恒 0 而恒假），不可用。
（附带原因：Steam 的 `PatchFlag` 根本不读 flag 1000，故原版「改 `start.ws2` 的 flag 1000」这条路线在 Steam 侧无效。）

### 7.2 交付形态

改动 3（4 个 `SL_*.ws2`）有两条交付路线。**「引擎读取裸 `RIO/`」已确认**——依据：官方预约特典「スウィートラブパッチ」只以裸 `RIO/` 形式发行（`start.ws2` + 4 个 `SL_*`），`Rio.arc` 内既无 `SL_*` 也未置 flag 1000，若不读裸目录该官方特典将完全无效；实机复现（覆盖 `RIO/SL_*.ws2` 即可从标题菜单进入后日谈）证明**归档内不存在的成员会从裸目录加载**。见 [engine-mechanics.md](engine-mechanics.md) §「磁盘裸 `RIO/` 目录：构成、来源与是否被引擎读取」。未定项仅剩**同名成员优先级**（裸文件 vs 归档内同名成员）。

| 路线 | 做法 | 前提 |
|---|---|---|
| **A. 归档重建** | 把 `SL_*.ws2` 打进 `asset/Rio.arc` | 无（一定可行） |
| **B. 裸目录覆盖** | 交付 `RIO/SL_*.ws2` 裸文件，**与原版特典同形** | 读取裸目录 ✅（实机：`Rio.arc` 内无 `SL_*`，覆盖后仍能进入后日谈）；同名成员的**优先级**待测 |

路线 B 可省去归档重建、天然满足「零破坏性」，且**与原版发行形态一致**；路线 A 是保底。

> **裁定**：4 个 `SL_*.ws2` 走**路线 B（裸 `RIO/`）**；`start.ws2` 走**就地修改**（不交付裸覆盖）；`CO1_001/002/003/015`、`HUT_004/005` **不引入**。⚠️ 但**引用资源**另有归档路由障碍（Steam 不加载 `PVOICE/PCHIP/PBGM`），见 §9.4。

### 7.3 不得改动项

1. `mainmenu.ws2`、`REPLAY_EXE.ws2`、`FLAG_CHECK.ws2` —— 两版对应关系已确证，改动即引入偏移风险。
2. `ui_button.lua`、`menu_base.lua` —— 按钮类与 `bt_*` 的唯一实现处，全工程共用。
3. 成就触发点（922 处 / 51 脚本 + `0xF0` 29 处）—— 原样保留指令与成就 id，不新增、不补钩子。见 [restoration-targets.md](restoration-targets.md) 贯穿约束与 [engine-mechanics.md](engine-mechanics.md) §成就触发点契约。
4. `SL_*.ws2` 尾部的 `SetFlag 126 = 0` + `NextFile "TITLE"` —— 返回机制依赖。

### 7.4 需求映射

| 需求 | 实现位置 | 状态 |
|---|---|---|
| ① 主界面新增 "Sweet Love" 入口按钮 | main.133.8 pc 188–278 + `Sys_title.pna` 层 54/55/56 | ✅ 既有，需解 G1 |
| ② 海报悬停高亮、否则灰色 | `SYS_After.pna` 层 8–11（高亮）／14–17（灰态）+ `menu_base` 按钮状态机 | ✅ 既有 |
| ③ 每条后日谈按对应线路解锁 | §1.2（选择界面逐条判定） | ✅ 既有 |
| ④ 入口需通关后才可点 | main.133.8 pc 362–397 | ⚠️ 原版为 **5 线全通**；若要「一条即亮」须改写该判定链 |

---

## 8. 未定项与风险

1. ✅ **引擎读取裸 `RIO/`**（官方特典「スウィートラブパッチ」只以裸 `RIO/` 发行，不读则特典完全无效；实机覆盖 `RIO/SL_*.ws2` 亦生效）。**残留**：**同名成员**（归档内已存在该成员时）裸文件是否优先，待实机 A/B —— 当前裁定不依赖它（`SL_*` 归档内不存在，`start.ws2` 走就地修改）。见 [engine-mechanics.md](engine-mechanics.md)。
2. ✅ **选择界面匹配性**：`openSceneSelect`（Steam 侧原为无调用点的死代码）经 G2 改名接入后，实机可完成「sweet 按钮点亮 → 海报选择写入 `var99` → 进入并跑通 `SL_KOT_001`」。其余三条同一分支形态，未逐条实机。若海报与子层出现错位，退路是照原版 main.210 用 `menu_base` API 重写。
3. ⚠️ **取消路径过渡**：原版 `openAfter` 的 `RU` 分支写 `SetVariable(99, 0)` + `MenuEffectToMenu(500)`；Steam 写 `SetVariable(99, -1)` + `rtSnap`。`mainmenu.ws2` 对 `var99 ∈ {0, −1}` 均无匹配分支 ⇒ 落到 `0x048d Jump 20` 重新初始化主菜单。两版行为等价，但 Steam 缺 `MenuEffectToMenu` 淡出过渡，可能表现为硬切。
4. **需求④ 语义差异**：原版要求 5 线全通才点亮 sweet 入口；若产品要求「通关一条即可点」，须改写 main.133.8 pc 362–397 的判定链。
5. **`PatchFlag` 恒真后**，未全通关时 sweet 按钮仍会**创建**（走 pc 188–278 分支），但由 pc 362–397 呈**灰态／不可点**，符合需求②③。

---

## 9. 执行方案

### 9.1 交付形态（用户裁定）

1. **4 个 `SL_*.ws2` 走磁盘裸 `RIO/` 目录**（与原版スウィートラブパッチ同形），**不进 `Rio.arc`**。
2. **`start.ws2` 就地修改，不走裸覆盖** —— 在归档内改，不交付裸 `RIO/start.ws2`。理由：原版裸文件用 `PULLTOP_LOGO_BLUE.PNG`、Steam 用 `MOENOVEL_LOGO.PNG`，直接覆盖会顶掉 Steam 的 logo。
3. **忽略** `CO1_001/002/003/015.ws2`、`HUT_004/005.ws2`（属 L5）。
4. **33 张后日谈分层立绘（G9）不由 L4 交付**：这 33 名全部被原版主线脚本引用 ⇒ 归本体线的缺失资源工序并入 `GRAPHIC.arc`，L4 只按名端到端验收（`python script/build_l4.py --verify <产物目录或 GRAPHIC.arc>`）。

### 9.2 改动清单（精确偏移）

| # | 目标 | 改动 | 位置 |
|---|---|---|---|
| **G1** | `Script.arc` → `LegacyGame.lua` | `49 c0 c6 8b` → `49 00 c9 8b`（解除 `PatchFlag` 硬置 false） | 成员内 **`0x234b0`**（4 B） |
| **G2** | `Script.arc` → `LegacyGame.lua` | 字符串常量项 `\x04 <len=16> "openSceneSelect"\0` → `\x04 <len=10> "openAfter"\0`（**长度前缀与含 NUL 的字节块一起改**，15 字符 → 9 字符）—— 直接接上 `mainmenu.ws2` 的 `ExecuteFunction "openAfter"` | 成员内 **`0x2a18`**（全库唯一一处） |
| **G3** | 裸 `RIO/SL_{KOT,AGE,AMA,HUT}_001.ws2` | 从原版裸 `RIO/` 回填并转成 **Steam WS2 编码**：语义零改动，只有「补插恒为 0 的新操作数」＋「跳转偏移重定基」两类编码适配（见 §5.4 与 [file-formats.md](file-formats.md)） | 源：原版 `RIO/`；构建器 `script/convert_sl_ws2.py` |
| **G4** | `Rio.arc` → `start.ws2` | `SetFlag 1000` 0→1：解码偏移 **5** 的 `00`→`01`；原始文件（rotate-6）同偏移 `00`→**`04`** | 成员偏移 **`0x05`** |
| **G5** | `zh-CN/Rio.arc` | 追加 4 个 `SL_*.lng`：构建时从 `resource/fan_cn/SL_*.json` 现做（`tool/fancn.load_texts` → `tool/lng.encode_lng`，XOR 0x88），不留档 | 见 §9.3 |
| **G6** | `Script.arc` → `ArcFileName.lua` | 注入 `GetFlag(126) == 1` 归档路由分支（**A2 精简**：graphics +66 条 → `PChip.arc`、sound +34 条 → `PVoice.arc`，**不含 `bgm` 子块**） | 插入点 graphics pc 18 / sound pc 27；构建器 `script/build_l4.py` |
| **G7** | `PVOICE.arc` / `PCHIP.arc` | 原版**整档复制**（1253 个 `*_100xx.ogg` / 126 个 `*_P*_*.png`），裸归档放游戏根目录 | 源：原版根目录 |
| **G8** | `SE.arc` | 追加 3 个 `PSE` 独有 SE（`T_se91.ogg`／`pw129_4.ogg`／`se43b.ogg`） | 见 §9.7-3 |
| **G9** | `GRAPHIC.arc`（**L4 不写盘**） | 33 个后日谈 PNA 分层立绘由**本体线**并入 `GRAPHIC.arc`；L4 按名单逐一断言产物含这 33 名，并复核名单未漂移（原版有／Steam 基线无）。缺则 `st01` 等立绘槽加载 `Bあげは_01L.pna` 失败并报 `サブプレイヤーが存在しません`；名单见 `script/build_l4.py` `SL_PNA` | 验收器 `script/build_l4.py --verify` |
| **G10** | `zh-CN/Rio.arc` | `NameTable.txt` 合并 L2 的 `resource/fan_cn/NameTable.json`（99 条日文名牌键；读取时把组合名中点 `·` 归一为官方用字 `・`）。官方表只覆盖英文键，还原脚本的 `%LC小鳥` 等查不到会裸显日文；机制见 [file-formats.md](file-formats.md) §NameTable，L4 侧不维护条目，只逐一断言 `SL_*` 用到的 8 个键在表内（名单 `script/build_l4.py` `SL_NAME_KEYS`） | 构建器 `script/build_nametable.py` |

**G3 跳转重定基约束**：插入式编码转换必须重定基**所有**携带绝对偏移的跳转。每个 `SL_*` 只有 **2 条 `0x01.b` ＋ 1 条 `0x06`** 的目标因插入而改变（4 个文件合计 8 + 4 处），二者分属两条不同路径：

| 携带者 | 门控 | 生效路径 | 处理 |
|---|---|---|---|
| 尾部 `01.b → 续场段` ×2 | `flag[127]==1` / `var[110]==18..21`，**条件不成立才跳** | **正常路径**（标题菜单 → 海报 → `SL_*`）的 **H 场景→下一场景退出口** | 必须重定基 |
| 头部 `06 → 场景入口` | 上面同一对守卫，**条件成立才走到** | **仅回想路径**；而 Steam 版回想入口结构性缺失（§5.3）⇒ **实际不可达** | 必须重定基（不可达代码同样要自洽） |
| 头部 `01.b → 0x25` ×2 | — | 两条路径都执行，但目标在插入点之前、值不变 | 无需处理 |

门控变量的**唯一写入点**（全库 159 成员 ＋ Script.arc 全部 Lua 扫描）：`flag127` = 回想模式标记，仅 `mainmenu.ws2 @0x308` 置 1（`var99 == 2` 回想按钮分支）；`var110` 先由 `menu_gallery.lua` 写页内序号、再仅由 `REPLAY_EXE.ws2` 改写为全局序号 1–21（后日谈四条为 18/19/20/21，写后立即 `flag126 = 1` → `NextFile SL_*`）。海报入口路径（`var99 == 105` → `openAfter` → `flag126 = 1` → `NextFile SL_*`）**不触碰 127** ⇒ 头部 `06` 在正常路径不可能执行。

⇒ 尾部那对 `01.b` 是**正常路径必然执行**的退出口：漏重定基会把 PC 跳进 `0x14` 台词操作数中部，到不了续场段（`0b flag[1068]=1` → `timer01` → 下一场景 BG），实机表现为「H 场景结束后回到当前场景」无限循环 ＋ 循环后 BGM 消失（续场段的 `1f`/`65` 从未执行）。
⇒ 头部 `06` 只有 2 字节（目标低半字节，4 文件共 8 字节），作用域是回想路径；该路径在 Steam 版结构性不可达（§5.3）⇒ 无实机可观察效果，也**无回归风险**。仍必须重定基：线性解析下不可达代码同样要与 Steam 编码自洽，否则目标落进流中部，一旦入口被启用即崩溃。

回读断言：Steam 表解析指令数/操作码序列/操作数/尾部一致 ＋ 每个重定基后的目标都落在指令起点。SL 脚本 H 场景完全自包含（不跳 `CO1_*`）。⚠️ 插入取值**不靠** `CO1_*`/`HUT_*` 配对校准（两版正文已分化，指令流无法逐条对齐，详见 [file-formats.md](file-formats.md) §两版操作数格式表）；取值依据是 Steam 自身 159 个成员里该字段的实际分布。

**G2 是纯字节操作**：Lua 字节码字符串自带长度前缀、跳转全为**相对偏移** ⇒ 改长度无需修正任何偏移，也不需要 Lua 编译器。§4.2 的转发函数写法仅作备选。

### 9.3 文本层

文本主产物是逐脚本 JSON：`resource/fan_cn/SL_{KOT,AGE,AMA,HUT}_001.json`（875 / 851 / 714 / 788 槽，按原版 idx）。`.lng` 是引擎装载形态，**构建时现做**：`tool/fancn.load_texts()` 按 idx 展开槽位（空洞为空串）→ `tool/lng.encode_lng(key=0x88)` → 直接封进 `zh-CN/Rio.arc`，L4 无翻译工作量，也不保留 `.lng` 留档。

**不留档的依据**：留档与主产物分属两次重建会**静默落后** —— 重跑文本层只刷新 JSON，磁盘上的 `.lng` 停在上一波，且没有任何断言会因此变红。失步量级的实测见 [script-text-extraction.md](script-text-extraction.md) §6「装载形态不留档」。按需生成后该失步类别不存在。

现做口径的复核：104 个脚本按 JSON 现做的 `.lng` 与此前留档**逐字节相同**（`SL_*` 4 个 0 差异槽），且 G5 改读取源前后 `zh-CN/Rio.arc` md5 相同 ⇒ 施工层生成与旧留档等价，文本改动必然落到产物。

### 9.4 资源归档路由（⚠️ 关键，决定 G6 走法）

**原版有两个归档路由函数，都在 `LegacyGame.lua` 里**（它们是 Lua 全局函数，由引擎／脚本在取资源时调用，返回值 = 该资源所在归档名）：

| proto | 行号 | 函数 | 作用 |
|---|---|---|---|
| `main.41` | 1134–1242 | `getGraphicsArcFileName` | 立绘／CG／UI 图 → `Chip*.arc` / `Graphic.arc` / `SysGraphic.arc` / `PChip.arc` / `Chip+.arc` |
| `main.42` | 1245–1298 | `getSoundArcFileName` | 语音／BGM／SE → `Voice.arc` / `Bgm.arc` / `Se.arc` / `SysVoice.arc` / `PVoice.arc` / `PBgm.arc` / `Voice+.arc` |

**两个路由共用同一个开关：`GetFlag(126) == 1`** —— 即「当前正在跑后日谈（`SL_*`）场景」。

**⚠️ 两个参数用途不同，必须区分**：

| 参数 | 含义 | 用途 |
|---|---|---|
| **第 1 个**（`R0`） | 引擎构造的**资源标识**，含类别子串（`char`／`bgv`／`bgm`／`age`…） | 全部 `find` 判定 |
| **第 2 个**（`R1`） | **文件名**（如 `AGE_1309.ogg`） | 仅 sound 的 3 条特例 `sub(R1,1,8)` |

**实测：文件名本身不含 `char`/`bgv`/`bgm`** —— `PVOICE.arc` 的成员名是 `AGE_10001.ogg`、`KOT_0387.ogg`、`YOR_10001.ogg` 这类。
⇒ 判定**不以文件名为输入**，命中的是引擎传入的**类别标识**（第 1 个参数）。

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
  sub(R1,1,2) == "bg"    → Chip1.arc
  sub(R1,1,3) == "sky"   → Chip1.arc ；"age" → Chip2.arc ；"ama" → Chip6.arc
                "com"      → Chip2.arc ；"hut" → Chip3.arc ；"kot" → Chip5.arc
  sub(R1,1,4) == "sdev"  → Chip2.arc
  sub(R1,1,2) == "an" / "ef" → Chip4.arc ；sub(R1,1,3) == "est" → Chip4.arc ；"im" → Chip4.arc
  默认                     → Graphic.arc
```

**⚠️ `voice`／`bgm`／`se` 的分流不是三个函数，而是同一个 `getSoundArcFileName` 内部的 `find` 子串链**（原版 `main.42` = 152 条指令）。要点：

- 判定输入一律是 **R0（引擎构造的类别标识）**，`char` 与 `bgv` **都返回 `Voice.arc`**（两个子串 → 同一归档）；
- **`se` 没有任何正面判定** —— 它是链尾的**兜底**（pc149 `LOADK "Se.arc"` → pc150 `RETURN`），语义是「不是 char/bgv/bgm/systemvoice 的一律算 SE」；
- **优先级**：3 条 `Voice+` 特例（用 **R1 文件名**、`sub(R1,1,8)`、**无条件、不看 flag 126**）→ `flag 126` 分支 → 常规链 → `Se.arc` 兜底；
- `flag 126` 分支内三个子串都不匹配时**不是返回，而是 fall through 到常规链**（pc50 的 `JMP +42` 只在 flag≠1 时跳；flag=1 且都不匹配则顺序走到 pc93 的常规链，最终仍落 `Se.arc`）。

⇒ **`PSE.arc` 在 Lua 里没有任何分支可达**，它若被加载只能是引擎侧的挂载行为，见 §9.7-4。

**⇒ `flag 126` 是后日谈资源的归档路由开关**（与它作为「跳过标记」的双重身份一致：`mainmenu.ws2`／`REPLAY_EXE.ws2` 跳 `SL_*` 前置 1、`SL_*` 尾部置 0 ⇒ 只有后日谈场景运行期间为 1）。
**`flag 1000` 与此无关**——它的作用是原版 `main.196` 的 `MenuInf.PatchFlag = GetFlag(1000)`（「Sweet Love 已安装」总开关，由 `start.ws2` 置 1）。

**Steam 把这两个路由搬到 Steam 独有的 `ArcFileName.lua`**（`LegacyGame.inc` 末行 `include "ArcFileName"`），并**删掉了 `GetFlag(126)` 分支、`Chip+` 特例、`Voice+` 特例与全部 P* 归档**：
- `getSoundArcFileName`：`SysVoice`→SysVoice.arc／`char`/`bgv`→Voice.arc／`bgm`→Bgm.arc／`systemvoice`→SysVoice.arc／默认→Se.arc（**无 `age_1309`/`kot_0387`/`kot_3837` 特例**）
- `getGraphicsArcFileName`：按名字前缀 → `sys_`→SysGraphic.arc、`efmsk`→Graphic.arc、`bg`/`sky`→Chip1、`age`/`com`/`sdev`→Chip2、`hut`→Chip3、`an`/`ef`/`est`/`im`→Chip4、`kot`→Chip5、`ama`→Chip6、默认→Graphic.arc（**无 `sys_arrow`/`sys_configp7`/`sys_dialog`/`sys_log` 特例**）
- `getRioArcFileName`→Rio.arc；`getModelArcFileName`→Model1.arc
- ⚠️ Steam `getSoundArcFileName`（`main.3`，86 条）的 **pc0–26 是死代码**：`NEWTABLE` 建空表 + `pairs({})`，循环体（按语言拼 `SysVoice` 前缀做 `find`）**永不执行** ⇒ 真正的判定链**从 pc27 开始**，这正是 A 路线把插入点取在 **27** 的原因（死代码之后、首个 `char` 判定之前）

**⇒ 数据端在 Steam 已完整**：`mainmenu.ws2` 与 `REPLAY_EXE.ws2`（两版字节相同）跳 `SL_*` 前均已 `SetFlag 126 = 1`，`SL_*` 尾部 `SetFlag 126 = 0` ⇒ **只差路由端这一个分支**。

**`Chip+`／`Voice+` 特例分支不需要还原**（属 L5，Steam 已内含，实测见 §9.7-6）。

| 路线 | 做法 | 代价 |
|---|---|---|
| **A1 完整复刻** | 各加 `GetFlag(126) == 1` 分支（graphics 4 条 → `PChip.arc`；sound 3 条 → `PVoice.arc`／`PBgm.arc`）；交付 4 个 `P*` | 交付 ≈ 334 MB；与原版形态完全一致 |
| **A2 精简复刻**（**采用**，= §9.2 G6/G7/G8） | **只路由真正不同的部分**：graphics 4 条 → `PChip.arc`；sound **2 条**（`char`／`bgv`）→ `PVoice.arc`；**不加 `bgm` 分支**；交付 `PVOICE`＋`PCHIP` 2 个 + **3 个** SE 并入 `SE.arc` | 交付 ≈ **296 MB**（省 `PBGM` 33 MB＋`PSE` 1.9 MB）；少 14 条指令；行为与原版**完全等价**（跳过的内容与主线 md5 相同） |
| **B 并入主线归档**（备选，不改 Lua 时的最优） | 把后日谈资源**按名字前缀**并入 Steam **已有**归档（见 §9.7-7 净新增清单）；`PBGM` 15 个与 `PSE` 22 个**直接跳过** | **完全不改 Lua**；净新增 1489 个成员、零实质冲突；须重建 5 个主线归档，但**只需在表末尾追加**，已有成员 `rel_offset` 不变。可行性依据：后日谈语音经 `find(R0,"char")` 走 `Voice.arc`，而 `PVOICE` 的 1253 个与 `VOICE.arc` **0 同名** ⇒ 并入即命中目标归档 |

`ArcFileName.lua` 已有 `getJPatchFlag()` 调用先例、`LegacyGame__lua_GetFlag` 绑定可用 ⇒ 路线 A 在绑定层面可行；字节层面的实现见 §9.5。路线 B 不需要动它。

### 9.5 路线 A 的字节级实现

**结论：不需要 Lua 5.1 编译器。** 实现 = `script/build_l4.py` 的 `inject_route_branches()`（G6）：把原版 `main.41`／`main.42` 的 flag 126 分支整块搬进 Steam `ArcFileName.lua`，输出可被完整反汇编回读。

**三条支撑事实**

1. **常量表追加在末尾 ⇒ 已有指令的 `Bx`／`RK` 索引全部不变。** 新常量按值复用 Steam 已有项（`string`／`sub`／`lower`／`1.0`／`3.0`／`age`／`ama`／`hut`／`kot`／`find`／`char`／`bgv`／`bgm`／`nil`…），缺的才追加。
   - `main.1`（graphics）：31 → 36 常量，新增 `cfunc`／`LegacyGame__lua_GetFlag`／`126.0`／`1`／`PChip.arc`
   - `main.3`（sound）：14 → 20 常量，新增 `cfunc`／`LegacyGame__lua_GetFlag`／`126.0`／`1`／`PVoice.arc`／`PBgm.arc`
2. **插入块内部全为相对跳转 ⇒ `sBx` 与原版逐条相同，可原样复制。** 原版 `JMP pc += 60`（graphics）／`JMP pc += 42`（sound）在块内位置恰好等于块长度，逐位吻合。
3. **插入点前后都没有需要修正的跳转。** 插入点（graphics = Steam `main.1` pc **18**；sound = Steam `main.3` pc **27**）之前的 `JMP` 目标也在插入点之前；之后的 `JMP` **全部是 `sBx = +2` 的局部短跳**。⇒ **零跳转修正。**

**改动量（实测）**

| proto | code | 常量 | maxstack | 插入位置 |
|---|---|---|---|---|
| `main.1` graphics | 216 → **282**（+66） | 31 → 36 | 11（原版块只用 R4–R9，**无需提升**） | pc 18（`efmsk` 判定之前） |
| `main.3` sound | 86 → **134**（+48） | 14 → 20 | 15（原版块只用 R6–R8，**无需提升**） | pc 27（`char` 判定之前） |

**验证结果**：插入点之后的所有指令**逐条完全未变**（差异 0 条）；`EQ 0 R5 1`（A=0 ⇒ `==`）与原版一致；补丁文件整体可被 `lua51dis.py` 完整解析（`protos total=5`，字节流长度自洽）。

**另需同步**：`lineinfo` 数组在 Steam 侧已被 strip（`nli == 0`），**无需同步插入**（`luaU_undump` 不校验 `sizelineinfo == sizecode`）。成员变大后须用 `tool/arcbuild.py` 重建 `Script.arc`。

**实测提醒**：`getJPatchFlag()` 在 Steam `main.1` 的 pc 0–1 被调用但返回值从未被读（`local patch = getJPatchFlag()` 的死代码，分支体已删）⇒ **不能复用 `getJPatchFlag` 做 126 分支**，必须新调 `cfunc.LegacyGame__lua_GetFlag(126)`。

**A2 精简变体（当前交付采用，只路由真正不同的部分）**：去掉末尾的 `bgm` → `PBgm.arc` 子块后，sound 块 **48 → 34 条**，**只需修正块首那一条 `JMP` 的 `sBx`（42 → 28）**，其余全部不变。回读反汇编落点正确（插入点 pc 27 + 34 = 61），常量映射中不再出现 `PBgm.arc`。
依据：`PBGM.arc` 的 15 个成员与主线 `BGM.arc` **md5 完全相同**（§9.7-3），让 `bgm` 走常规 `Bgm.arc` 行为完全等价 ⇒ 可省 33 MB 交付。`script/build_l4.py` 即按此形态注入（sound 块只含 `char`/`bgv`）。

> **⚠️ 措辞红线**：跳过的是**待注入的 `flag 126` 块里**的 `bgm` 子块（即「不搬」这一子块），**不是删除 Steam 常规链里的 `find(R0,"bgm") → Bgm.arc`**。后者是主线 BGM 的唯一路由，删掉会让全游戏 BGM 落入 `Se.arc` 兜底而全部失效。
> 同理，`char`/`bgv` 子块**不能省** —— `PVOICE` 的 1253 个与 `VOICE.arc` **0 同名**，省掉就是真缺语音。

### 9.6 资源盘点

| 类型 | Steam 缺失 | 原版位置 |
|---|---|---|
| `.ogg` | 1256 | **`PVOICE.arc` 1253**（全部为 10000 段语音，**仅被 4 个 `SL_*` 引用**）＋ `PSE.arc` **3**（`T_se91`／`pw129_4`／`se43b`）；`PSE` 剩余 22 个与 `SE.arc` 同名（md5 全同 ⇒ 跳过） |
| `.png` | 139 | **`PCHIP.arc` 126** |
| `.pna` | **33** | **原版 `GRAPHIC.arc`**（5 位女主后日谈分层立绘 `A小鳥/Bあげは/C天音/D亜紗/E夜瑠_0X_[L/M/W].pna`；路由按默认分支 → `Graphic.arc`，与 flag 126 无关 ⇒ 须并入 `GRAPHIC.arc`；该并入属本体线缺失资源工序，L4 只验收（见 §9.2 G9））。另：`EST_2302.PNG`/`EST_334.PNG`（仅 `SL_HUT_001` 各引用 1 次）**原版发行版亦缺**，属原版 Sweet Love 补丁自身缺口，按零破坏纪律保持原样 |

⚠️ 「哪儿都找不到」的残留清单必须用**完整名匹配**复核：朴素正则会把前置操作码字节混进文件名（如 `fEFMSK_11.PNG` 实为 `EFMSK_11.PNG`，Steam `GRAPHIC.arc` 已有），Shift-JIS 成员名同样会被截断；复核后仅 `EST_2302/334.PNG` 这类为真缺。

### 9.7 P* 归档的实质与实测比对 ✅

**1. `P*` 归档 = 后日谈（`flag 126 = 1`）运行期的独立资源域**，命名规则 = `P` + 主线归档名：

| P* 归档 | 对应主线 | 成员数 | 文件大小 | 时间戳 |
|---|---|---|---|---|
| `PVOICE.arc` | `VOICE.arc` | 1253 | 68 MB | 2012-05-06 |
| `PBGM.arc` | `BGM.arc` | 15 | 33 MB | 2012-05-06 |
| `PSE.arc` | `SE.arc` | 25 | 1.9 MB | 2012-05-06 |
| `PCHIP.arc` | `CHIP2/3/5/6.arc`（多对一） | 234 | 228 MB | 2012-05-06 |

**2. 内容自包含 —— 4 条 `SL_*` 的引用 100% 落在 `P*` 内**（大小写不敏感全名匹配）：

| P* 归档 | 被 4 条 SL 引用 |
|---|---|
| `PVOICE` | **1253 / 1253（100%）** |
| `PBGM` | **15 / 15（100%）** |
| `PSE` | **25 / 25（100%）** |
| `PCHIP` | 127 / 234 —— 其余 107 个是 **`.MOS`** 等同名衍生文件（引擎按基名自动关联，脚本不直接引用） |

⇒ **`P*` 存在的意义**：让引擎在「路由函数返回唯一归档名 ⇒ 只在该归档里查找」的模型下，后日谈能完整运行，同时**不污染主线归档**。

**3. 因此 `P*` 里必须包含主线资源的副本**（要自包含，主线已有的也得复制一份）：

| 对比 | 结果 |
|---|---|
| `PBGM.arc` 15 个 vs `BGM.arc` 同名成员 | **md5 全部相同（15/15）** |
| `PSE.arc` 22 个 vs `SE.arc` 同名成员 | **md5 全部相同（22/22）**；`PSE` 独有 **3 个**：`T_se91.ogg`、`pw129_4.ogg`、**`se43b.ogg`**（Steam 有 `se43a` 无 `se43b`） |
| `PCHIP.arc` vs `CHIP6.arc` 同名成员 | 1 个：`AMA_08_002S.png`，**md5 相同** |
| `PVOICE.arc` vs `VOICE.arc` | **0 个同名**（1253 个全部为后日谈新增） |

**4. ⚠️ 未定项：`PSE.arc` 在 Lua 里不可达**（`SE` 是链尾兜底，无正面判定，见 §9.4）
`getSoundArcFileName` 的 `flag 126` 分支只处理 `char`/`bgv`/`bgm`，默认分支**无条件**返回 `Se.arc` —— **没有任何分支返回 `PSE.arc`**。但 4 条 SL 引用了 `PSE` 全集（含 **3 个** `SE.arc` 里没有的 `T_se91.ogg`、`pw129_4.ogg`、`se43b.ogg`）。

两个可证伪的假设（**一次实机即可判定**）：

| 假设 | 内容 | 依据 |
|---|---|---|
| **H1 常驻挂载**（推荐） | 引擎无条件挂载 `P*` 归档，与 `flag 126`／Lua 路由无关 | 与スウィートラブパッチ「散装文件补丁包」的发行形态吻合，也解释了 `P*` 为何**自带主线副本**（`PBGM` 15／`PSE` 22，即 PSE 25 个中与主线同名的部分）做自包含 |
| H2 从不加载 | `PSE` 只是发行冗余，后日谈里那 3 个独有 SE 实际取不到（静音） | 与「Lua 无分支可达」的字面结论一致 |

**验证方法**：① 在主线任意脚本把某 SE 调用临时改成 `T_se91`（`PSE` 独有）→ 出声 = H1，无声 = H2；② 或把 `PSE.arc` 改名后跑到后日谈对应位置 → 该 SE 失效 = H1，无变化 = H2。⚠️ 本交付**不携带 `PSE.arc`**（3 个独有 SE 已按 G8 并入 `SE.arc`）⇒ 方法②只能在原版基线上做。

⇒ **无论 H1/H2，A2 与 B 都不受影响**：两条路线都把 3 个独有 SE 并入 `SE.arc`、`PBGM`/`PSE` 主体跳过（内容都能在主线归档找到）⇒ 交付体积 344 MB → 296 MB（`PVOICE` 68 + `PCHIP` 228）。
（H2 情形下并入反而会「修好」原版实际取不到的那 3 个 SE —— 属超出原版的无害增强。）

**5. `PCHIP.arc` 全量比对 —— 234 个里 233 个是纯新增**（按前缀 vs Steam 现有路由落点）：

| 前缀 | 数量 | 扩展名 | Steam 路由落点 | 同名冲突 |
|---|---|---|---|---|
| `AGE` | 76 | PNG 47 + **MOS 29** | `CHIP2.arc` | **0** |
| `AMA` | 63 | PNG 32 + **MOS 31** | `CHIP6.arc` | **1**（`AMA_08_002S.png`，**内容相同**） |
| `HUT` | 42 | PNG 27 + **MOS 15** | `CHIP3.arc` | **0** |
| `KOT` | 53 | PNG 32 + **MOS 21** | `CHIP5.arc` | **0** |

对照全部主线图形归档（`Chip1`/`CHIP2`/`CHIP3`/`CHIP4`/`CHIP5`/`CHIP6`/`GRAPHIC`）逐一比对，**唯一同名只有 `AMA_08_002S.png`（且 md5 相同）**。
⇒ **PCHIP 的 234 个成员可以整体并入 Steam 现有归档，零实质冲突**（那 1 个直接跳过）。
⇒ `.MOS` 是立绘的衍生文件（引擎按基名自动关联），**必须与 `.PNG` 一并搬运**。

**6. `Voice+`／`Chip+` 属 L5，不属本任务** —— 机制与实测见 `doc/engine-mechanics.md`（v1.02 章节）。
同一对路由函数里还有 3 + 4 条 `+` 系列**无条件**特例分支（`sub(R1,1,8)` → `Voice+.arc`；`sub(R1,1,9)` → `Chip+.arc`），它们是 **v1.02 修正补丁的载体**（时间戳吻合：`Chip+` 05-22 ↔ `CO1_*` 05-22；`Voice+` 05-29 ↔ `HUT_004/005` 05-29），**与后日谈无关**。实测 Steam 基线**已内含**其修正 ⇒ **两条分支都不需要还原**，路线 A 的改动范围确认 = 只还原 `flag 126` 分支（graphics 4 条 + sound 3 条）。

**7. 路线 B 的净新增清单与前提**

**「只处理真正不同的部分」正是路线 B 的形态** —— 净新增如下，其余全部跳过：

| 资源 | 数量 | 并入目标 | 同名冲突 | 依据 |
|---|---|---|---|---|
| 后日谈语音 | **1253** | `VOICE.arc` | **0** | `PVOICE` 与 `VOICE.arc` **同构**（`AGE_0001.ogg` ↔ `AGE_10001.ogg`：同前缀、同扩展名，只差编号段）⇒ 引擎构造相同类别标识 ⇒ 同走 `char`/`bgv` → `Voice.arc` |
| 后日谈立绘 | **233** | `CHIP2`(76)／`CHIP6`(62)／`CHIP3`(42)／`CHIP5`(53) | **1**（`AMA_08_002S.png`，内容相同 ⇒ 跳过） | §9.7-5 |
| 后日谈 SE | **3** | `SE.arc` | **0** | `T_se91.ogg`／`pw129_4.ogg`／`se43b.ogg`（`PSE` 独有） |
| `PBGM` 15 首 | **0** | — | — | 主线 `BGM.arc` 已有**同名同内容**（md5 全同）⇒ 跳过 |
| `PSE` 22 个 | **0** | — | — | 主线 `SE.arc` 已有**同名同内容**（md5 全同）⇒ 跳过 |

**合计净新增 1489 个成员**（语音 1253 + 立绘 233 + SE 3），零实质冲突。

> 这 3 个 SE 在 Steam `SE.arc` **均无同名** ⇒ 按 [resource-naming.md](resource-naming.md) **直接继承原名**（SE 无固定编号制，不适用号段）。同理，后日谈立绘 233 个中除 `AMA_08_002S.png` 外**全部无同名** ⇒ 也直接继承原名（保持场景段 `08`），号段 `8X` 因此在本层暂未启用。

**前提 / 风险**：
1. **引擎能加载成员数变化的主线归档**（`VOICE.arc` 21499 → 22752）—— 格式未变，风险低，**须实机验证一次**。
2. **追加方式**：`tool/arcbuild.py` 的 `write_arc` 从 `[(name, data)]` 重建；因 `rel_offset` 相对 `8 + table_size`，**新成员追加在列表末尾即可**，已有成员偏移不变（也可做「原地追加」以省内存，不必把 828 MB 读进内存）。
3. **交付形态耦合**：路线 B 把 L4 资源并进主线归档 ⇒ 若 L4 要做成**独立补丁包**则不合适（此时选路线 A）；若 L4 与主还原**同一补丁包**、或主还原本来就要重建这些归档，则 B 是**零额外成本**。

## 10. 与本体还原线（L1–L3）的工序分工

**判据：引用面。** 除 `SL_*` 外是否也被**非 `SL_*` 的原版脚本**引用 —— 被主线引用 ⇒ 本体还原顺带就该解决，属**前置**工序，L4 只校验；只有后日谈引用 ⇒ L4 专属；本体范围天然覆盖不到的 FD 增量 ⇒ L4 **按需加工**。

### 10.1 引用面实测

扫描范围：原版 `Rio.arc`（160 个 `.ws2`，**不含 `SL_*` 成员**）+ 原版裸 `RIO/`（11 个 `.ws2`，含 4 个 `SL_*`）+ Steam `Rio.arc`，解码后按字节搜索。
⚠️ 脚本内的资源名一律**大写带扩展名**（`T_SE91.OGG`、`SE43A.OGG`），与归档成员名（`T_se91.ogg`）**不同形** ⇒ 引用面搜索必须大小写不敏感，否则会误判成零引用。

| 交付项 | 引用面 | 归属 | L4 侧动作 |
|---|---|---|---|
| **G9** 33 张分层立绘 `.pna` | **33/33 被原版主线脚本引用**（每名 16–2569 处）；Steam 脚本**零引用**；`SL_*` 亦引用每名 1–105 处 | **L3** 缺失资源工序（无同名冲突 ⇒ 继承原名，见 [resource-naming.md](resource-naming.md)） | **不搬运文件**；对产物 `GRAPHIC.arc` 逐名断言这 33 名在位（`script/build_l4.py --verify`） |
| **G10** `NameTable.txt` 补充 | 名牌族只有 `%LC` 一族（脚本侧 63074 处引用、196 个去重键）；**非 ASCII 键 100 个，官方表 94 键全 ASCII ⇒ 覆盖 0 个**；引用面 = 仅主线 **92** ／ 主线+FD **7** ／ 仅 FD **1**。L2 产物 `resource/fan_cn/NameTable.json`（99 条，**覆盖这 100 个键里的 99 个、零冗余键**；未覆盖的 1 个键引用面为**仅主线** ⇒ **`SL_*` 用到的 8 个键（7 共用 + 1 专属）全部命中，L4 侧零缺口**） | **L2/L3 的 zh-CN 构建**（`script/build_nametable.py` 是唯一的合并出口：官方保序在前 + 日文键追加） | 构建器直接消费 `resource/fan_cn/NameTable.json`（组合名中点在读取时 `·`→`・` 归一）；L4 侧**不维护条目**，只按 `SL_NAME_KEYS` 断言这 8 键在合并表内。消费前提见 §10.3 |
| **G8** 3 个 `PSE` 独有 SE | `T_se91`（`SL_AMA_001`）、`pw129_4`（`SL_HUT_001`）**仅 `SL_*` 引用**；`se43b` 另被原版 `AMA_010`、`KOT_003` 引用，而 Steam 脚本无此引用 ⇒ 该引用属被阉割的本体内容 | `se43b` → **L3**；其余 2 个 → L4 | 校验 `SE.arc` 含 3 名 |
| **G7** `PVOICE`（1253 个语音基名） | **全部仅 `SL_*` 引用** | L4 | 保持 |
| **G7** `PCHIP`（138 个 PNG 基名） | 127 个被 `SL_*` 引用；91 个被非 `SL_*` 引用，但其中 **90 个的这类引用只来自 `CG_PAGE12`** —— 后日谈 CG 相册页的条目表（该成员含内嵌数据表，线性解析会失步，见 [file-formats.md](file-formats.md) 的「Steam 表覆盖缺口」；Steam 侧该页数据仍保留）；余下 1 个是 `AMA_08_002S`（唯一同名同内容者，`AMA_009`/`CG_PAGE04`/`CG_PAGE06` 命中皆由此） | L4（"主线引用"实为后日谈数据页） | 保持 |
| **G3** 原版→Steam 的 WS2 编码转换 | 两版操作数格式差分 + 跳转重定基对「插回原版段落」同样必需；`0x1c`／`0x35`／`0x56` 三条格式差尚未纳入当前转换表 | **前置为本体线公共工序** | 复用同一转换器，不维护 FD 专用分支 |
| **G1/G2/G4/G6** | 后日谈门控与归档路由（`flag126`、`openAfter`、`start.ws2`、`ArcFileName.lua`） | L4 | 保持 |
| **G5** `SL_*.lng` | 内容仅 FD；**工序**（主产物 JSON → 引擎 `.lng`）与本体线同口径（`tool/fancn.load_texts` + `tool/lng`），但**不共用留档文件** | L4（内容） | 构建时现做（§9.3） |

### 10.2 顺序与接口

1. **本体先行**：L1–L3 的交付应包含 33 张 `.pna`、`se43b`、以 L2 的 `resource/fan_cn/NameTable.json` 为来源合并出的**全量** `%LC` 日文键名牌表（官方 94 键 + 100 个日文键，见 §10.3），以及通用的原版→Steam WS2 编码转换能力。
2. **L4 校验**：L4 构建前逐项按名断言「交付归档含该成员」「NameTable 含该键」「`SL_*.ws2` 经公共转换器回读通过」；断言失败的缺口若落在主线引用面 ⇒ **回报本体线**，不在 L4 内代做。
3. **按需加工**：只有 FD 需要且本体范围天然不覆盖的增量由 L4 追加 —— 资源写进各自归档；名牌表 L4 **无自有条目**（§10.1 的 G10 行）。号段约定（`9X` 归 L1–L3、`8X` 归 L4）**仅在同名冲突改名时启用**，无冲突仍继承原名，因此两线并载同名资源不会撞名。

⇒ L4 的净自有交付 = **门控与路由（G1/G2/G4/G6）+ 后日谈独有资源（G7、`T_se91`、`pw129_4`）+ FD 文本层（G5）**；G10 的条目全部来自 L2 表（L4 只消费 + 断言），G9 的文件由本体线搬运（L4 只按名验收），`se43b` 同理应由本体线交付。

**执行口径**：`script/build_l4.py` 不产出 `GRAPHIC.arc`，因此 L4 的独立输出树**不足以**完整实机验证后日谈（立绘槽会报 `サブプレイヤーが存在しません` 类加载失败）；后日谈的实机与端到端验收一律在本线产物（或游戏目录）上跑 `--verify`。

### 10.3 消费 L2 名牌表（`resource/fan_cn/NameTable.json`）的前提

该表是 `script/build_fan_translations.py` 的产物（日文说话名不进正文、只进这张表，且显示名已过假名/占位符门禁），覆盖 §10.1 那 100 个非 ASCII 键里的 **99 个**，且不含脚本未引用的冗余键。它不能单独成为成品表，L4 的接入方式是把它作为补充条目喂给 `script/build_nametable.py`（这张 JSON 是补充条目的唯一来源；显示名要改就走机械层 `tool/textfix.py` 的 `NAME_FIX`，重建后落进 JSON）。以下四项分别是消费约束（1、2）与归属本体线的对账（3、4）：

1. **必须与官方 94 键合并**。`build_fan_translations.py --emit-lng` 写出的 `NameTable.txt` **只含这 99 条、不含官方英文键** ⇒ 若用它建 `zh-CN/Rio.arc`，Steam 原生英文底本的名字串（`%LCKotori` 等）会全部查不中而裸显英文。合并出口只能是 `script/build_nametable.py`（官方保序在前 ⇒ 同键覆盖 ⇒ 新键追加），两线共用。
2. **组合名分隔符归一在读取时进行，不回写 L2 产物**：官方值域用 `・`(U+30FB)，出现 9 次（7 个组合值），`·`(U+00B7) 在官方值域**零出现**；本表 9 个组合值用的是 `·`，其中 **7 个**官方有同名组合（`%LCあげは・小鳥`→扬羽·小鸟 对官方 `%LCAgeha,Kotori`→扬羽・小鸟），统一为 `・` 后即逐字一致；余下 2 个（`%LC亜紗・依瑠`、`%LC碧・小鳥・亜紗・依瑠`）官方无对应组合，归一后仍是本表自有译法。本表**键**用的已是 `・`（9 个组合键），归一只动值 ⇒ 不会产生新键或撞键。
3. **与官方英文表逐名对账**：99 个值里 38 个已在官方值域内（如 全员／小鸟／扬羽／云雀），61 个自造（多为配角，例：`%LCハット`→哈特、`%LCイスカ`→易鸟、`%LC先生`→先生、`%LC気象学者`→气象学者）；按第 2 条归一后自造数降到 **54**。反向可量化冲突面：官方 94 键中有 **48 条**（未归一时 55 条）的中文值没有被本表任何一个值用到，其中相当一部分与本表某条日文键疑似指向同一人（官方 `%LCTeacher`→老师 / 本表 `%LC先生`→先生；官方 `%LCIsuka`→伊斯卡 / 本表 `%LCイスカ`→易鸟；官方 `%LCAgeha's mother`→姬城妈妈 / 本表 `%LC姫城母`→姬城母亲；官方 `%LCTouring Club Staff`→机车社员 / 本表 `%LCツーリング部員`→旅游部员；官方 `%LCMeteorologist`→空中观察员 / 本表 `%LC気象学者`→气象学者）。两线并载时同一人物的名字串会分别命中英文键与日文键 ⇒ 同人不同译上屏，需按这 48 条逐条裁决同人关系再定名。**这项对账属本体线**：`SL_*` 用到的 8 个键中 **6 个与官方逐字相同**（小鸟／扬羽／天音／亚纱／依瑠／碧，各与一个英文键 1:1），余 2 个是官方无对应的组合名 ⇒ FD 侧不存在与官方冲突的人名。
4. **1 个键补表也查不中**：`%LC%XS35ト　　　ビ　　　ウ　　　オ　　　荘%K%P` —— 名字串里嵌了 `%XS` 场景标记、全角空格和行尾 `%K%P`，而引擎查表是**整串精确匹配** ⇒ 官方表与本表都没有它。引用面为仅主线（原版 `Rio.arc`、裸 `RIO/` 各 1 处，`SL_*` 无）；这类要按 `0x15` 操作数的实际语义判定（名牌被标记切碎），属遗留缺陷，不在补表范围内。

⇒ **L4 侧的落地形态**：`script/build_nametable.py` 以这张 JSON 为补充条目来源（读取时 `·`→`・` 归一），`script/build_l4.py` 用 `SL_NAME_KEYS` 断言 `SL_*` 的 8 个日文键都在合并表内。1、2 两项是**消费方式**的约束，3、4 两项是**归属本体线**的待办。

## 11. 参考

| 对象 | 路径 |
|---|---|
| Steam 基线 | `backup/`（只读） |
| 原版脚本 | 原版发行版的 `Rio.arc`、`Script.arc`（外置，见文首基线说明；其裸 `RIO/` 含 `SL_*.ws2`） |
| Steam 脚本 | `backup/Rio.arc`、`backup/Script.arc` |
| Lua 反汇编器 | `tmp/lua51dis.py`（Lua 5.1 undump 解析 + 反汇编；`tmp/` **未纳入版本管理**。**直接命令行调用**：`python tmp/lua51dis.py <file.lua> [--list\|--grep <s>\|--func <n 或 main.41>]`） |
| Lua 路由注入 | `script/build_l4.py`（G6：常量追加 + 分支插入 + 序列化回写，**纯字节，无需 Lua 编译器**；原理见 §9.5） |
| 归档读写 | `tool/arcbuild.py`；WS2 编解码 `tool/ws2.py`；PNA 图层 `tool/pna.py` |
| 原版 WS2 反汇编 | `tool/ws2dis.py` + 原版引擎格式表，见 §5.2 |
