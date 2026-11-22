# 后日谈（After Story）机制与改动点

> 状态图例：✅ 已确认 ／ ⚠️ 部分确认（静态证据充分，未实机验证） ／ ❓ 未知
> 本文只写**后日谈机制与改动点**（依据：文件／指令号／量级）。精确字节偏移、构建器、构建期断言、资源盘点的施工口径见 [restoration-route.md](restoration-route.md) §4.1；文件格式与字节布局见 [file-formats.md](file-formats.md)；归档路由函数等引擎侧行为见 [engine-mechanics.md](engine-mechanics.md)。
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

回想入口（`REPLAY_EXE.ws2`）是另一条独立路径：按「页码 + 页内序号」选定条目 → **改写 `var110 = 18/19/20/21`** → `SetFlag 126 = 1` → `NextFile SL_*`；进入后 `SL_*` **头部**守卫 `flag[127] == 1 ∧ var[110] == 18..21` 成立 ⇒ 走到那条 `06` 直跳 H 场景入口（跳过整条路线的前段）；**尾部**同一对守卫成立 ⇒ 落到 `07 NextFile EVRET`，由 `EVRET`（4 条指令：`var110 >= 18` 则清 `flag126`，随后 `NextFile TITLE`）回收。正常路径（标题菜单 → 选择界面）**不置 `flag127`** ⇒ 头部守卫不成立、不执行那条 `06`，从头播整条路线；尾部守卫同样不成立 ⇒ 依「条件不成立才跳」的引擎语义跳到续场段（`0b flag[1068] = 1` → `timer01` → 下一场景 BG），不经过 `EVRET`。跳转携带者与重定基要求见 [file-formats.md](file-formats.md) §两版操作数格式表与原版脚本转换。

⚠️ **Steam 版该入口结构性不存在**：派发脚本 `REPLAY_EXE.ws2` 与原版逐字节相同，但 `menu_gallery.lua` 的回想数据只到 `REPLAY_017`、`SceneMenu.PageMax = 2`，而 `SL_KOT` 分支要「第 2 页第 9 条」、其余三条要「第 3 页」（`var101 == 3`）⇒ 四条分支全部取不到（推理见 §5.2）。因此 `SL_*` 头部那条 `06` 在 Steam 侧是**不可达代码**，后日谈验收只需覆盖海报入口一条路径。

### 0.2 变量契约

| 变量 | 写入者 | 语义 |
|---|---|---|
| `99` | 菜单按钮 `MenuButtonJob` | 被选中按钮的 id（标题菜单 100–105；后日谈选择界面 1–4；取消 = 0 或 −1） |
| `100` | 鉴赏菜单 | CG 页码 |
| `101` | `menu_gallery.lua`（**唯一写入者**，`LegacyGame__lua_SetVariable(101, g_GalleryInfo.ScenePage)`） | **回想页码**（不是分类）。Steam 侧 `SceneMenu.PageMax = 2` ⇒ 只能取 1/2；`REPLAY_EXE.ws2` 的后日谈分支要求 `== 3` ⇒ 不可达（见 §5.2） |
| `110` | 先由 `menu_gallery.lua` 写「页内序号」（`SceneButtonJob`），再由 `REPLAY_EXE.ws2` 用 `0x09` 改写成「全局序号」（**浮点变量**） | 全局序号：主线回想 1–17，后日谈 **18 / 19 / 20 / 21**；`SL_*` 头部/尾部守卫与 `EVRET` 都读它 |
| `126` | 派发脚本（**布尔位图**，`0x0b` 写） | 后日谈归档路由开关：跳 `SL_*` 前置 1，`SL_*` 尾部或 `EVRET` 置 0（路由语义见 §9.1） |
| `127` | `mainmenu.ws2 @0x308`（唯一写入点；离开时 `@0x182` 置 0） | **回想模式标记**（布尔位图）。与 `var110` 一起构成 `SL_*` 头部/尾部那对守卫的条件 ⇒ 决定走「直跳 H 场景 + 退场经 `EVRET`」还是「整条路线 + 续场段」 |
| `1000` | `start.ws2` | **Sweet Love 总开关**（原版裸 `RIO/start.ws2` = 1；arc 内 = 0） |
| `1001`–`1005` | 各线通关脚本 | 路线通关标记（见 §1.1） |

### 0.3 三处缺口（开发要补的全部内容）

| # | 缺口 | 位置 | 量级 |
|---|---|---|---|
| **G1** | 入口开关被硬置 `false` | `LegacyGame.lua` main.133 pc 90 | **2 字节** |
| **G2** | 选择界面函数改名后无人调用（孤儿） | `LegacyGame.lua` main.140 `openSceneSelect` | **1 处字符串常量** |
| **G3** | 4 个 `SL_*.ws2` 从 `Rio.arc` 删除 | `Rio.arc` | 4 脚本 + 引用资源 |

⇒ **除这三处外，机制链的脚本端在 Steam 版逐环节完整存在**（按钮代码、按钮图形、选择界面、脚本派发表、回想派发表、回主菜单尾跳）。⚠️ 回想入口的**数据端**除外：`menu_gallery.lua` 的条目表只到 17 条／2 页 ⇒ 该入口在 Steam 不可达，可达入口只有标题菜单 sweet（§5.2）。另有两类**资源端**缺口不在「脚本端完整」的结论内：归档路由分支被删（§9.1，`flag 126`）与原版独有资源（§9.2）。

### 0.4 原版发行形态

原版 Sweet Love 以**磁盘裸目录 `RIO/` 覆盖归档**的形式发行（11 个 `.ws2`）：`start.ws2`（195 B，`SetFlag 1000 = 1` 总开关）、`SL_KOT/AGE/AMA/HUT_001.ws2`（125452／131040／102980／134054 B，4 条后日谈本体）、`CO1_001/002/003/015.ws2` 与 `HUT_004/005.ws2`（H 场景出入口，属 L1–L3）。这些裸文件是**已解码明文**，可直接作为 L4 内容来源。

对照 Steam `Rio.arc`：4 个 `SL_*` **完全缺失**；`CO1_*`、`HUT_004/005`、`start.ws2` 存在但**内容不同**（Steam 版更大）。

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

两版命中集**逐条相同**（另有 1008 / 1009，与后日谈无关）⇒ **解锁数据在 Steam 版完整保留。**

### 1.2 读取端 A：选择界面逐条解锁

| 按钮 | 原版 `openAfter`（main.210，扁平序 #372） | Steam `openSceneSelect`（main.140，扁平序 #253） | 解锁条件 |
|---|---|---|---|
| 1 | `SC01`，id = 1 | `Scene1`，id = 1 | `GetFlag(1001) ~= 0` |
| 2 | `SC02`，id = 2 | `Scene2`，id = 2 | `GetFlag(1003) ~= 0` |
| 3 | `SC03`，id = 3 | `Scene3`，id = 3 | `GetFlag(1004) ~= 0` |
| 4 | `SC04`，id = 4 | `Scene4`，id = 4 | `GetFlag(1002) ~= 0 and GetFlag(1005) ~= 0` |

各条满足即 `MenuButtonData.<名字>:bt_SetActive(2.0)`（解除灰态）。原版 main.210 pc 110–159；Steam main.140.2（`TrialInit`）pc 43–92 ⇒ **逐条等价**。第 4 条（HUT）需 **ASA 与 YOR 双线通关**，与 `SL_HUT_001` 的剧情定位一致。

### 1.3 读取端 B：标题入口总开关

**前置**：原版只看 `MenuInf.PatchFlag`；Steam 另要求 `g_TrialFlag == 0`。**判定**：两版同为 `GetFlag(1001) ∧ (GetFlag(1002) ∧ GetFlag(1005)) ∧ GetFlag(1003) ∧ GetFlag(1004)`（Steam pc 362–392，`1002` 与 `1005` 先做 `and`），成立则 `MenuButtonData.sweet:bt_SetActive(2.0)`（pc 393–397）⇒ **语义等价**。

⇒ **入口点亮条件是 5 条线全部通关**（不是「通关一条」）；未全通关时按钮仍存在但为灰态、不可点。

### 1.4 `PatchFlag` 的来源（G1 的成因）

原版 main.196 pc 22–25 `MenuInf.PatchFlag = GetFlag(1000)`；Steam main.133 pc 82–86 `= GetFlag(1005)`，**pc 90 随即 `= false`** ⇒ **恒 false**。

`start.ws2` 对 flag 1000 的赋值：原版 `Rio.arc` **0**；原版裸 `RIO/start.ws2`（195 B）**1**（「Sweet Love 已安装」的开关）；Steam `Rio.arc`（126 B）**0**。

⇒ Steam 侧是**双重关闭**：数据源写 0 + 代码硬置 `false`。G1 只需解开后者（§7.1）。

### 1.5 辅助派生

`FLAG_CHECK.ws2`（`Rio.arc`，两版**字节完全相同**，415 B）由路线标记派生辅助标记 120–124 与配置项 id 51（`0x0d 33 00 01 00 00 00 40` ＝ 配置 51 置 `3.0`）。

### 1.6 `bt_SetActive` 的定义位置 ✅

**在 `ui_button.lua`**（Steam 新增模块，`LegacyGame.inc` 已 include）：该模块 pc 92 `SETTABLE R15[K47('bt_SetActive')] := R16`，同处定义全部 `bt_*`（`bt_SetOnOffActive`／`bt_SetEnableSubLayer`／`bt_ResetActive`／`bt_SetColor`／`bt_PlayAnim`／`bt_MovableStart`…）。原版这些方法内联在 `LegacyGame.lua` 内，Steam 抽出为独立模块 ⇒ Steam 侧可直接调用，**不是引擎绑定，无跨版本风险**。

## 2. 调用链与既有实现位置

| 环节 | 原版 `LegacyGame.lua` | Steam `LegacyGame.lua` | 状态 |
|---|---|---|---|
| 标题菜单主体／初始化／按钮子函数 | main.196 `titleMenu`（#304）／`titleMenu` pc 0–…／main.196.2 | main.133 `GameTitle`／main.133.8 `TitleMenuInit`／main.133.3 | ✅ 既有 |
| 按钮类与 `bt_*` | 内联在 `LegacyGame.lua` | **`ui_button.lua`** | ✅ 既有 |
| 入口开关 | `PatchFlag = GetFlag(1000)` | `PatchFlag = GetFlag(1005)` 后**强制 `false`** | ⚠️ **G1** |
| 选择界面 | main.210 `openAfter`（#372） | **main.140 `openSceneSelect`（#253）** | ⚠️ **G2**（改名 + 无调用点，但 `mainmenu.ws2` 仍调 `openAfter`） |
| 后日谈脚本 | 裸 `RIO/SL_*.ws2` | **缺失** | ⚠️ **G3** |
| 归档路由 | `LegacyGame.lua` main.41／main.42 | **`ArcFileName.lua`（已删 `flag 126` 分支）** | ⚠️ **G6**（§9.1） |

其余环节两版结构一致、Steam 侧原样存在，无需改动：按钮图形（`Sys_title.pna` 67 层，层 54/55/56 = sweet 三态）、选择界面图形（`SYS_After.pna` 20 层）、脚本派发（`mainmenu.ws2` 已含 `openAfter` 与 4×`SL_*` 分支，§5.1）、回想派发（`REPLAY_EXE.ws2` 与原版**字节完全相同**，837 B）、回主菜单（`SL_*` 尾部 `NextFile "TITLE"`，§6）。

## 3. 入口机制（标题菜单 sweet 按钮）✅

### 3.1 既有实现契约（G1）

`LegacyGame.lua` main.133（`GameTitle`）pc 82–90：`g_Menu.GameTitle.ptr.PatchFlag = GetFlag(1005)`，随后 **pc 90 立即 `SETTABLE ptr["PatchFlag"] = K27(bool false)`**。常量表（main.133 共 46 项）相关三项：`K26 = 1005.0`（亦在 pc 109 的 `GetAllClearFlag` 链复用）、`K27 = false`（pc 90／143）、`K36 = true`（pc 148）⇒ **G1 = 把 pc 90 的 C 操作数由 `K27` 改为 `K36`**。

⇒ **`K26` 不得改为 `1000.0`**：pc 109 的 `GetAllClearFlag = 1001∧1002∧1003∧1004∧GetFlag(K26)` 会因 flag 1000 恒 0 而恒假。

`main.133.8`（`TitleMenuInit`）的行为切分：**pc 185** 按 `PatchFlag` 分岔 —— 真分支 pc 188–278 建 **6 键布局**（含 `MenuAnimButtonSet("btnState2", …, "sweet", 54/55/56, id = 105)`），假分支 pc 279–353 建 5 键布局（**无 sweet**）；**pc 356** 要求 `g_TrialFlag == 0`（它在 main.0 pc 141–142 初始化为 `0.0`、全工程再无写入 ⇒ 恒 0 ⇒ 解锁块恒执行）；**pc 359–397** 在 `PatchFlag` 为真时取 `GetFlag(1001/1002/1003/1004/1005)`（`1002` 与 `1005` 先合），全真则 `MenuButtonData["sweet"]:bt_SetActive(2.0)`；pc 398–431 是 gallery／load 按钮的解锁与 `SetColor`。

图形资源：`Sys_title.pna`（`SysGraphic.arc`）两版头结构相同——`PNAP`，`unknown=2960`，1280×720，**67 层**；层 54/55/56 即 sweet 按钮三态（Steam 版图形存在、未阉割）。

### 3.2 行为契约

`PatchFlag` 真 + 5 线全通 ⇒ sweet **创建且可点**；真 + 未全通 ⇒ sweet **创建但灰态不可点**（需求②）；假（Steam 现状）⇒ 6 键布局整体走假分支、**无 sweet 按钮**。点击 sweet 时 `MenuButtonJob` 写 `var99 = 105`。

### 3.3 另一处独立开关（勿混）

`ui_language.lua` 的 `getJPatchFlag()`（`PatchFlag = false; return PatchFlag`，写的是**全局** `PatchFlag`）与标题菜单的 `GameTitle.ptr.PatchFlag` **字段**无关。它在 `LegacyGame.lua`／`menu_config.lua`／`menu_gallery.lua`／`ArcFileName.lua` 中被引用，属 L1–L3 的 H 内容开关范畴；与本项**互不干扰**，不能靠翻转 `getJPatchFlag` 顺带解决。

## 4. 选择界面机制 ⚠️（既有，需接线）

### 4.1 Steam `openSceneSelect`（main.140）与原版 `openAfter`（main.210）对照

| 项 | 原版 main.210 `openAfter` | Steam main.140 `openSceneSelect` |
|---|---|---|
| Menu 对象 / 子层 | `g_AfterMenu = Menu:new("AfterMenu")` / 基名 `AfterBace`，号 19 | `g_Menu.SceneSelect.ptr = Menu:new("SceneSelect")` / 基名 `SceneSelect01`，号 19 |
| 按钮 API / 名 / id | `MenuButton:ButtonCreate` + `SetList` / `SC01`…`SC04` / 1–4 | `MenuButtonSet`（Steam 新版 API）/ `Scene1`…`Scene4` / 1–4 |
| 初始化子函数 / 事件名 | `startAfter`（main.210.2）/ `LD` / `RU` | `TrialInit`（main.140.2）/ `LU` / `RU` |
| 解锁判定 / 收尾 | pc 110–159 ／ `NeedProcess(LUA_PROCESS_GAME_PAUSED, 0)` + `g_menuExecute = true` + `return true` | main.140.2 pc 43–92（逐条等价）／同 |
| **调用点** | `mainmenu.ws2` 的 `ExecuteFunction "openAfter"` | **无（孤儿函数）** |

两版 PNA 文件同为 `SYS_After.pna`。

`mainmenu.ws2`（Steam，1179 B）仍保留 `ExecuteFunction "openAfter"` 与 4 个 `SL_*` 分支 ⇒ 一旦 sweet 可点，脚本会调用一个**在 Steam 未定义的全局** `openAfter`。这是 G2。

### 4.2 接线契约（G2）

> **✅ 契约（G2）**：把 `LegacyGame.lua` 成员内 `0x2a18` 的字符串常量项 `\x04 <len=16> "openSceneSelect"\0` 就地改为 `\x04 <len=10> "openAfter"\0`（长度前缀与含 NUL 的字节块一起改，15 字符 → 9 字符）。该串全库**唯一一处**（即全局注册名），Lua 字节码字符串自带长度前缀、跳转全为**相对偏移** ⇒ **改长度无需修正任何偏移**，也不需要 Lua 编译器。

**不改 `mainmenu.ws2` 字符串**：`openAfter`（9 字符）→ `openSceneSelect`（16 字符）长度不等，需重建脚本并修正全部跳转偏移，违背「就地插入」纪律。若改名不可行，退路是在任一已被 `LegacyGame.inc` include 的模块末尾追加**转发函数** `function openAfter(...) return openSceneSelect(...) end`——必须用 `function` 而非赋值（赋值在模块加载时求值、捕获到 `nil`，加载顺序不保证）。

### 4.3 事件与 id 契约 ✅

Steam `GameTitle.MenuButtonJob`（main.133.5）与 `SceneSelect.MenuButtonJob`（main.140.1）**同用 `LU` 事件**，pc 25 都执行 `SetVariable(99, R1)`（按钮 id → 变量 99）；`GameTitle` 侧 pc 41 另有 `R1 == 105.0` 的 sweet 分支。⇒ `SceneSelect` 的按钮同样写出 `var99 = id`（1..4），与 `mainmenu.ws2` 的 `var99 == 1..4` 分支对齐。

### 4.4 可用 API 与资源 ✅

`menu_base.lua` 提供 `Menu:new`／`MenuInit`／`MenuButtonData`／`MenuButtonSet`／`MenuAnimButtonSet`／`MenuMoveButtonSet`／`MenuButtonInit`／`initSubLayer`／`setSubLayerParam`／`getSubLayerParam`／`MenuEffectStart/End/ToMenu`／`MenuMouseMove`／`MenuLButtonDown/Up`／`g_SysSEName`／`SystemSePlay` 等；`bt_*` 定义在 `ui_button.lua`（§1.6）。`SYS_After.pna`（`SysGraphic.arc`）两版头结构相同（`PNAP`，`unknown=892`，1280×720，**20 层**）：0 = 彩条遮罩、2–5 = 4 位女主海报、8–11 = 高亮态、14–17 = 灰态（需求②）。按钮 SE `SYS01.ogg`／`SYS03.ogg` 在**两版** `SE.arc` 中均存在。

### 4.5 未定项（§8-2）

`openSceneSelect` 在 Steam 属死代码，其子层基名 `SceneSelect01` 与 Steam `SYS_After.pna` 的实际匹配性、`MenuButtonSet` 参数表、取消路径过渡效果均需实机确认。

## 5. 派发机制 ✅

### 5.1 Steam `mainmenu.ws2`（`Rio.arc`，1179 B）派发表 ✅

```
0x0145  id99 == 105 → Jump 818
0x0332  ExecuteFunction "openAfter"              ← 调用 Lua 选择界面
0x0341  id99 == 1 → ClearLayer / SetBackground bg01 WHITE.PNG / StopMusic systembgm
                    / SetFlag 126 = 1 → NextFile "SL_KOT_001"
0x0394 / 0x03e7 / 0x043a  id99 == 2/3/4 → 同形 → SL_AGE_001 / SL_AMA_001 / SL_HUT_001
0x048d  Jump 20                                  ← 无匹配时重入主菜单
0x0492  FileEnd
```

其余分支（供对照，非后日谈）：`99 == 100` → `CO1_001`；`101`／`102` → 子菜单；`103` → 鉴赏；`104` → 退出；`99 == 1`（`0x0197` 段）→ `CG_PAGE01..12`；`99 == 2`（`0x02f8` 段）→ `REPLAY_EXE`。

**与原版（1099 B）逐条对应**：上表 5 条分支在 Steam 侧整体后移、语义逐条相同 —— `0x0136`（`Jump 799` → `0x031f`）↔ `0x0145`（`Jump 818` → `0x0332`）、`0x032d`↔`0x0341`、`0x0371`↔`0x0394`、`0x03b5`↔`0x03e7`、`0x03f9`↔`0x043a`。差异仅两处：Steam 在 4 个 `SL_*` 分支前各多一条 `StopMusic systembgm`；Steam 侧多出操作码 `0x84`（原版表该项为 NULL ⇒ 原版脚本里的 `0x84` 字节只是操作数，不是转场标记）——属演出指令层差异，见 [engine-mechanics.md](engine-mechanics.md)。反汇编原版 WS2 必须换成原版引擎自带的格式表（`AdvHD.exe` 文件偏移 `0x1212c0`），按 Steam 表硬解会切错指令边界（差分见 [file-formats.md](file-formats.md) §两版操作数格式表与原版脚本转换）。

⇒ **脚本层无需任何改动**，唯一前提是 §4.2 的 `openAfter` 能返回并写入 `var99`。

### 5.2 回想派发（`REPLAY_EXE.ws2`）

两版**字节完全相同**（837 B）。全表（`var101` = 回想页码，`var110` = 页内序号，命中后改写为全局序号再 `NextFile`）：

```
var101 == 1（第 1 页）var110 1..9  → 全局 1..9  → KOT_003 KOT_003 KOT_006 KOT_009 AGE_005 AGE_007 AGE_010 AGE_010 AMA_004
var101 == 2（第 2 页）var110 1..8  → 全局 10..17 → AMA_006 AMA_007 AMA_010 ASA_002 ASA_004 YOR_003 YOR_005 YOR_007
                      var110 == 9  → 全局 18 → SetFlag 126 = 1 → NextFile "SL_KOT_001"
var101 == 3（第 3 页）var110 1..3  → 全局 19/20/21 → 各自 SetFlag 126 = 1 → NextFile "SL_AGE_001" / "SL_AMA_001" / "SL_HUT_001"
否则                                   → NextFile "TITLE"
```

⇒ ⚠️ **这条路径在 Steam 版结构性不存在**：派发脚本完整（四条后日谈分支原样保留），但**数据端被砍** —— `menu_gallery.lua` 的回想条目表只到 `REPLAY_017`（flag 1050–1066）、`ThXLineMax × ThYLineMax = 3×3 = 9`/页、`SceneMenu.PageMax = 2`，而 `var101` 由其独家写入 ⇒ 取值只能 1/2。Steam 的 17 条 = 第 1 页 9 条 + 第 2 页 8 条 ⇒ 「第 2 页第 9 条」（`SL_KOT`）与整个第 3 页（`SL_AGE`/`SL_AMA`/`SL_HUT`）**都取不到**（原版 21 条／3 页才走得通）。⇒ 后日谈**唯一可达入口 = 标题菜单 sweet**，`SL_*` 头部那条 `06` 直跳在 Steam 侧为不可达代码。

### 5.3 两版 WS2 编码不完全兼容

**权威结论见 [file-formats.md](file-formats.md) §两版操作数格式表与原版脚本转换**（表来源、9 条格式差、插入取值依据、逐文件改动面与跳转重定基）。后日谈侧的要点只有三条：`SL_*` 用到的差异操作码共 6 个（`0x11`／`0x14`／`0x15`／`0x16`／`0x1e`／`0x28`）；差异只有「按 Steam 表补插恒为 0 的新操作数」与「跳转偏移重定基」两类，**语义零改动**；重定基需求来源 = 4 文件共 `0x01.b` 8 处 + `0x06` 4 处，其中尾部那对 `0x01.b` 在**正常路径必然执行**（漏重定基即无限循环）。

## 6. 返回机制（回主菜单）✅

4 个 `SL_*.ws2` 尾部结构一致：`0x0b 0x7e 0x00 0x00`（`SetFlag 126 = 0`，清除跳过标记）→ `0x07 "TITLE" 0x00`（`NextFile TITLE`）→ `0xff …`（`FileEnd`）。文件尾 `TITLE` 偏移：`SL_KOT_001` @0x1e9fd、`SL_AGE_001` @0x1ffd1、`SL_AMA_001` @0x19235、`SL_HUT_001` @0x20b97（转换后位置见 [file-formats.md](file-formats.md) §两版操作数格式表与原版脚本转换）。

`mainmenu.ws2`／`REPLAY_EXE.ws2` 在跳 `SL_*` 之前均已 `SetFlag 126 = 1` ⇒ **回主菜单天然成立，无需改动。** 各 `SL_*.ws2` 头部 `Condition(mode=130, id=110, ==18/19/20/21)` 与 `REPLAY_EXE.ws2` 跳转前 `LayerConfig(id=110, 18/19/20/21)` 一一对应，链路自洽。

## 7. 改动点（G1–G10）

### 7.1 改动清单（量级 + 机制理由）

| # | 改动点 | 量级 | 机制理由 |
|---|---|---|---|
| **G1** | `Script.arc` → `LegacyGame.lua` main.133 pc 90 的 C 操作数 `K27(false)` → `K36(true)` | **2 字节** | §1.4：Steam 双重关闭，数据源之外还硬置 `false` |
| **G2** | 同一成员 main.140 的全局注册名 `openSceneSelect` → `openAfter` | **1 处字符串常量** | §4.1：`mainmenu.ws2` 仍调 `openAfter`，改名后成孤儿 |
| **G3** | 4 个 `SL_*.ws2` 从原版裸 `RIO/` 回填并转为 Steam 编码 | 4 脚本（转换后各 +2.6～3.2 KB） | §0.4 成员缺失 + §5.3 编码差 |
| **G4** | `Rio.arc` → `start.ws2` 的 `SetFlag 1000` 0→1 | **1 字节** | §1.4：原版「Sweet Love 已安装」开关 |
| **G5** | `zh-CN/Rio.arc` 追加 4 个 `SL_*.lng` | 4 文件（875／851／714／788 槽） | 后日谈文本只在民汉 JSON 里（装载形态现做，[script-text-extraction.md](script-text-extraction.md) §5） |
| **G6** | `Script.arc` → `ArcFileName.lua` 两个路由函数各注入 `flag 126` 分支 | graphics +66／sound +34 条指令 | §9.1：Steam 删了该分支 ⇒ P* 归档不可达 |
| **G7** | 新增裸 `PVOICE.arc`／`PCHIP.arc`（原版整档复制） | 1253 + 234 成员（约 68 + 228 MB） | §9.2：P* 与主线归档 0 同名，路由只在该分支返回 |
| **G8** | `SE.arc` 追加 3 个 `PSE` 独有 SE（`T_se91`／`pw129_4`／`se43b`） | 3 成员 | §9.4：`PSE.arc` 在 Lua 不可达，随 `SE.arc` 交付 |
| **G9** | 33 张后日谈 `.pna` 并入 `GRAPHIC.arc`（**本体线交付**，L4 只按名验收） | 33 成员 | §10.1：引用面全在原版主线脚本 |
| **G10** | `zh-CN/Rio.arc` 的 `NameTable.txt` 合并 L2 表（**本体线构建**） | L4 只断言 8 个名牌键 | §10.1：名牌键来源与合并规则 |

**精确字节偏移、构建器、构建期断言、资源盘点与逐文件改动面见 [restoration-route.md](restoration-route.md) §4.1。** 本文只记「改动点 + 量级 + 机制理由」。

### 7.2 交付形态

**引擎读取裸 `RIO/`** 已确认（依据与判据见 [engine-mechanics.md](engine-mechanics.md) §磁盘裸 `RIO/` 目录）。**裁定**：

1. 4 个 `SL_*.ws2` 走**裸 `RIO/`**（与原版特典同形），**不进 `Rio.arc`** —— 交付面只有新增裸文件、不触碰既有归档，且与原版发行形态一致。
2. `start.ws2` 走**就地修改**，不交付裸 `RIO/start.ws2`（原版裸文件用 `PULLTOP_LOGO_BLUE.PNG`、Steam 用 `MOENOVEL_LOGO.PNG`，直接覆盖会顶掉 Steam 的 logo）。
3. `CO1_001/002/003/015.ws2`、`HUT_004/005.ws2` **不引入**（属 L1–L5 范围）。
4. 33 张后日谈分层立绘（G9）**不由 L4 交付**，归本体线并入 `GRAPHIC.arc`；L4 只按名端到端验收。

归档接线与「同一归档只允许一趟写盘」的合并方式见 [restoration-route.md](restoration-route.md) §1／§2 硬纪律 4／§4.1。

### 7.3 不得改动项

1. `mainmenu.ws2`、`REPLAY_EXE.ws2`、`FLAG_CHECK.ws2` —— 两版对应关系已确证，改动即引入偏移风险。
2. `ui_button.lua`、`menu_base.lua` —— 按钮类与 `bt_*` 的唯一实现处，全工程共用。
3. 成就触发点（922 处 / 51 脚本 + `0xF0` 29 处）—— 原样保留指令与成就 id，不新增、不补钩子（见 [restoration-targets.md](restoration-targets.md) 贯穿约束与 [engine-mechanics.md](engine-mechanics.md) §成就触发点契约）。
4. `SL_*.ws2` 尾部的 `SetFlag 126 = 0` + `NextFile "TITLE"` —— 返回机制依赖（§6）。

### 7.4 需求映射

| 需求 | 实现位置 | 状态 |
|---|---|---|
| ① 主界面新增 "Sweet Love" 入口按钮 | main.133.8 pc 188–278 + `Sys_title.pna` 层 54/55/56 | ✅ 既有，需解 G1 |
| ② 海报悬停高亮、否则灰色 | `SYS_After.pna` 层 8–11（高亮）／14–17（灰态）+ `menu_base` 按钮状态机 | ✅ 既有 |
| ③ 每条后日谈按对应线路解锁 | §1.2（选择界面逐条判定） | ✅ 既有 |
| ④ 入口需通关后才可点 | main.133.8 pc 362–397 | ⚠️ 原版为 **5 线全通**；若要「一条即亮」须改写该判定链 |

## 8. 未定项与风险

1. ✅ **引擎读取裸 `RIO/`**。**残留**：同名成员（归档内已存在该成员时）裸文件是否优先，待实机 A/B —— 当前裁定不依赖它（`SL_*` 归档内不存在，`start.ws2` 走就地修改）。见 [engine-mechanics.md](engine-mechanics.md)。
2. ✅ **选择界面匹配性**：`openSceneSelect`（Steam 侧原为无调用点的死代码）经 G2 改名接入后，实机可完成「sweet 按钮点亮 → 海报选择写入 `var99` → 进入并跑通 `SL_KOT_001`」。其余三条同一分支形态，未逐条实机。若海报与子层出现错位，退路是照原版 main.210 用 `menu_base` API 重写。
3. ⚠️ **取消路径过渡**：原版 `openAfter` 的 `RU` 分支写 `SetVariable(99, 0)` + `MenuEffectToMenu(500)`；Steam 写 `SetVariable(99, -1)` + `rtSnap`。`mainmenu.ws2` 对 `var99 ∈ {0, −1}` 均无匹配分支 ⇒ 落到 `0x048d Jump 20` 重新初始化主菜单。两版行为等价，但 Steam 缺 `MenuEffectToMenu` 淡出过渡，可能表现为硬切。
4. **需求④ 语义差异**：原版要求 5 线全通才点亮 sweet 入口；若产品要求「通关一条即可点」，须改写 main.133.8 pc 362–397 的判定链。`PatchFlag` 恒真后，未全通关时 sweet 按钮仍会**创建**（走 pc 188–278 分支），但由 pc 362–397 呈**灰态／不可点**，符合需求②③。
5. ⚠️ **`PSE.arc` 的加载语义**（§9.4）：Lua 侧无分支可达，是常驻挂载还是从不加载未定。

## 9. 后日谈资源域与归档路由

### 9.1 `flag 126` 是后日谈资源的归档路由开关 ✅

原版两个归档路由函数（`LegacyGame.lua` main.41 `getGraphicsArcFileName`／main.42 `getSoundArcFileName`）**共用同一个开关 `GetFlag(126) == 1`**，即「当前正在跑 `SL_*` 场景」——与它作为「跳过标记」的双重身份一致：`mainmenu.ws2`／`REPLAY_EXE.ws2` 跳 `SL_*` 前置 1、`SL_*` 尾部置 0 ⇒ 只有后日谈场景运行期间为 1。`flag 1000` 与此无关（它是标题菜单 `PatchFlag` 的来源，§1.4）。

- 该分支内：sound 把 `char`／`bgv` 路由到 `PVoice.arc`、`bgm` 到 `PBgm.arc`；graphics 把 `{age,ama,hut,kot}` 前缀路由到 `PChip.arc`。
- **Steam 把两个函数搬到 `ArcFileName.lua`**（`LegacyGame.inc` 末行 include）并**删掉了 `flag 126` 分支、`Chip+`／`Voice+` 特例与全部 P* 归档** ⇒ 后日谈资源落进主线归档名、P* 不可达。
- **数据端在 Steam 已完整**（两端 `SetFlag 126 = 1/0` 逐字节在位）⇒ **只差路由端这一个分支（G6）**。
- 函数完整语义（判定输入是引擎构造的类别标识而非文件名、`find` 子串链、`se` 是链尾兜底、`flag 126` 分支不匹配时 fall-through 到常规链、Steam 侧 pc0–26 死代码）见 [engine-mechanics.md](engine-mechanics.md) §归档路由函数（`ArcFileName.lua`）。

### 9.2 `P*` 归档 = 后日谈运行期的独立资源域 ✅

命名规则 = `P` + 主线归档名（`PVOICE`↔`VOICE`、`PBGM`↔`BGM`、`PSE`↔`SE`、`PCHIP`↔`CHIP2/3/5/6` 多对一）。**内容自包含**：4 条 `SL_*` 的引用 100% 落在 `P*` 内 ⇒ `P*` 存在的意义是「路由函数返回唯一归档名 ⇒ 只在该归档里查找」的模型下让后日谈自包含运行而不污染主线归档，因此 `P*` 里**必须包含主线资源的副本**。

**交付取舍（G7 只交付 `PVOICE` + `PCHIP`）**：

| 对比 | 结论 |
|---|---|
| `PBGM` 15 个 vs `BGM.arc` 同名 | **md5 15/15 全同** ⇒ 让 `bgm` 走常规 `Bgm.arc` 行为完全等价，可省 33 MB ⇒ G6 不注入 `bgm` 子块 |
| `PSE` 22 个 vs `SE.arc` 同名 | **md5 22/22 全同**；`PSE` 独有 **3 个**（`T_se91`／`pw129_4`／`se43b`，Steam 有 `se43a` 无 `se43b`）⇒ 并入 `SE.arc`（G8） |
| `PCHIP` vs `CHIP6.arc` 同名 | 1 个 `AMA_08_002S.png`，**md5 相同** |
| `PVOICE` vs `VOICE.arc` | **0 个同名**（1253 个全为后日谈新增）⇒ `char`／`bgv` 子块**不能省**（省掉就是真缺语音） |

⇒ **只交付 2 个 `P*` 归档**：`PVOICE.arc`（1253 成员）+ `PCHIP.arc`（234 成员），另 3 个独有 SE 并入 `SE.arc`。成员数、体积与逐档核对见 [restoration-route.md](restoration-route.md) §4.1。

> ⚠️ **措辞红线**：跳过的是**待注入的 `flag 126` 块里**的 `bgm` 子块（不搬这一子块），**不是删除 Steam 常规链里的 `find(R0,"bgm") → Bgm.arc`** —— 后者是主线 BGM 的唯一路由，删掉会让全游戏 BGM 落入 `Se.arc` 兜底而全部失效。

### 9.3 `PCHIP` 的构成与计数口径 ✅

**成员总数 234 = `.png` 138 + `.mos` 96**（96 张 `.png` 各有同名 `.MOS` 伴生；`.MOS` 是立绘的马赛克衍生文件、引擎按基名自动关联 ⇒ 必须与 `.png` 一同搬运，见 [file-formats.md](file-formats.md) §`.MOS`）。

`.png` 的计数口径（**引用面与交付量一律用 126，不用 127／138／139**）：

| 口径 | 数 | 说明 |
|---|---|---|
| `PCHIP` 的 `.png` 成员总数 | **138** | 归档成员表全量 |
| 被 4 条 `SL_*` 引用的 `.png` 名 | **127** | 含唯一同名同内容者 `AMA_08_002S.png` |
| 其中 Steam 全库无同名（真新增） | **126** | = 127 − 1；**G7 需补的 `.png` 数**，也是并入主线时的净新增数 |
| 朴素正则读出的「Steam 找不到」个数 | 139 | **不作口径**：11 个伪缺口（`fEFMSK_*` 实为 `EFMSK_*`、前置操作码字节被误当名字，Steam `GRAPHIC.arc` 已有）+ 2 个原版亦缺（`EST_2302`／`EST_334`）|

⇒ **引用面计数必须按完整名匹配**（Shift-JIS 成员名同样会被截断），否则会把「Steam 已有」误算成缺口。

### 9.4 ⚠️ 未定项：`PSE.arc` 在 Lua 里不可达

`getSoundArcFileName` 的 `flag 126` 分支只处理 `char`/`bgv`/`bgm`，其余一律落链尾 `Se.arc` 兜底 —— **没有任何分支返回 `PSE.arc`**，但它若被加载只能是引擎侧的挂载行为。两个可判定的假设：**H1 常驻挂载**（引擎无条件挂载 `P*`，与 `flag 126`／Lua 路由无关；与官方特典「散装文件补丁包」的发行形态吻合，也解释了 `P*` 为何自带主线副本做自包含）／**H2 从不加载**（`PSE` 只是发行冗余，那 3 个独有 SE 实际取不到）。

**判定方法**：把 `PSE.arc` 改名后跑到后日谈对应位置 —— 该 SE 失效 = H1，无变化 = H2（本交付**不携带 `PSE.arc`**，只能在原版基线上做）。⇒ **无论 H1/H2，交付形态不变**：3 个独有 SE 已按 G8 并入 `SE.arc`，`PBGM`/`PSE` 主体跳过（内容都能在主线归档找到）；H2 情形下并入反而「修好」原版实际取不到的那 3 个 SE —— 属超出原版的无害增强。

## 10. 与本体还原线（L1–L3）的工序分工

**判据：引用面。** 除 `SL_*` 外是否也被**非 `SL_*` 的原版脚本**引用 —— 被主线引用 ⇒ 本体还原顺带就该解决，属**前置**工序，L4 只校验；只有后日谈引用 ⇒ L4 专属；本体范围天然覆盖不到的 FD 增量 ⇒ L4 **按需加工**。

### 10.1 引用面实测

扫描范围：原版 `Rio.arc`（160 个 `.ws2`，**不含 `SL_*` 成员**）+ 原版裸 `RIO/`（11 个 `.ws2`，含 4 个 `SL_*`）+ Steam `Rio.arc`，解码后按字节搜索。
⚠️ 脚本内的资源名一律**大写带扩展名**（`T_SE91.OGG`、`SE43A.OGG`），与归档成员名（`T_se91.ogg`）**不同形** ⇒ 引用面搜索必须大小写不敏感，否则会误判成零引用。

| 交付项 | 引用面 | 归属 | L4 侧动作 |
|---|---|---|---|
| **G9** 33 张分层立绘 `.pna` | **33/33 被原版主线脚本引用**（每名 16–2569 处）；Steam 脚本**零引用**；`SL_*` 亦引用每名 1–105 处 | **L3** 缺失资源工序 | **不搬运文件**；对产物 `GRAPHIC.arc` 逐名断言这 33 名在位 |
| **G10** `NameTable.txt` 补充 | `SL_*` 用到的 8 个日文名牌键（7 共用 + 1 专属）全部命中 L2 表 ⇒ **L4 侧零缺口**（键覆盖与官方对账见 [script-text-extraction.md](script-text-extraction.md) §5.1；合并规则与消费方见 [file-formats.md](file-formats.md) §`NameTable.txt`） | **L2/L3 的 zh-CN 构建** | 只按 `SL_NAME_KEYS` 断言这 8 键在合并表内，**不维护条目** |
| **G8** 3 个 `PSE` 独有 SE | `T_se91`（`SL_AMA_001`）、`pw129_4`（`SL_HUT_001`）**仅 `SL_*` 引用**；`se43b` 另被原版 `AMA_010`、`KOT_003` 引用而 Steam 脚本无此引用 ⇒ 该引用属被阉割的本体内容 | `se43b` → **L3**；其余 2 个 → L4 | 校验 `SE.arc` 含 3 名 |
| **G7** `PVOICE`（1253 个语音基名） | **全部仅 `SL_*` 引用** | L4 | 保持 |
| **G7** `PCHIP`（138 个 `.png` 基名，§9.3 口径） | 127 个被 `SL_*` 引用；91 个被非 `SL_*` 引用，但其中 **90 个的这类引用只来自 `CG_PAGE12`** —— 后日谈 CG 相册页的条目表（该成员含内嵌数据表，线性解析会失步，见 [file-formats.md](file-formats.md) 的「Steam 表覆盖缺口」；Steam 侧该页数据仍保留）；余下 1 个是 `AMA_08_002S`（唯一同名同内容者） | L4（「主线引用」实为后日谈数据页） | 保持 |
| **G3** 原版→Steam 的 WS2 编码转换 | 两版操作数格式差分 + 跳转重定基对「插回原版段落」同样必需 | **前置为本体线公共工序**（[file-formats.md](file-formats.md) §两版操作数格式表与原版脚本转换） | 复用同一转换器，不维护 FD 专用分支 |
| **G1/G2/G4/G6** | 后日谈门控与归档路由（`flag126`、`openAfter`、`start.ws2`、`ArcFileName.lua`） | L4 | 保持 |
| **G5** `SL_*.lng` | 内容仅 FD；工序（主产物 JSON → 引擎 `.lng`）与本体线同口径，但**不共用留档文件** | L4（内容） | 构建时现做（[script-text-extraction.md](script-text-extraction.md) §5） |

### 10.2 顺序与接口

1. **本体先行**：L1–L3 的交付应包含 33 张 `.pna`、`se43b`、以 L2 的 `resource/fan_cn/NameTable.json` 为来源合并出的**全量** `%LC` 日文键名牌表，以及通用的原版→Steam WS2 编码转换能力。
2. **L4 校验**：L4 构建前逐项按名断言「交付归档含该成员」「NameTable 含该键」「`SL_*.ws2` 经公共转换器回读通过」；断言失败的缺口若落在主线引用面 ⇒ **回报本体线**，不在 L4 内代做。
3. **按需加工**：只有 FD 需要且本体范围天然不覆盖的增量由 L4 追加。号段约定（`9X` 归 L1–L3、`8X` 归 L4）**只服务真新增资源**；**同名内容差一律整名覆盖** ⇒ 不改名、不占号段，后日谈侧**无「同名而内容不同」的成员**（唯一同名者 `AMA_08_002S` 系同名同内容）⇒ 覆盖方针在 L4 无适用面，只在主线 CHIP／GRAPHIC 工序里生效。

⇒ L4 的净自有交付 = **门控与路由（G1/G2/G4/G6）+ 后日谈独有资源（G7、`T_se91`、`pw129_4`）+ FD 文本层（G5）**；G10 的条目全部来自 L2 表（L4 只消费 + 断言），G9 的文件与 `se43b` 由本体线交付（L4 只按名验收）。

**执行口径**：`script/build/build_l4.py` 不产出 `GRAPHIC.arc`，因此 L4 的独立输出树**不足以**完整实机验证后日谈（立绘槽会报 `サブプレイヤーが存在しません` 类加载失败）；实机与端到端验收一律在本线产物（或游戏目录）上跑 `--verify`。

## 11. 参考

| 对象 | 路径 |
|---|---|
| Steam 基线／脚本 | `backup/`（只读）：`Rio.arc`、`Script.arc`、`zh-CN/Rio.arc` |
| 原版脚本 | 原版发行版的 `Rio.arc`、`Script.arc`（外置，见文首基线说明；其裸 `RIO/` 含 `SL_*.ws2`） |
| 归档读写 | `tool/arcbuild.py`；WS2 编解码 `tool/ws2.py`；PNA 图层 `tool/pna.py` |
| WS2 反汇编 | `tool/ws2dis.py` + 操作数格式表 `tool/ws2fmt.txt`（Steam）／原版引擎表（`AdvHD.exe` 文件偏移 `0x1212c0`）；两版差分见 [file-formats.md](file-formats.md) §两版操作数格式表与原版脚本转换 |
| Lua 路由注入 | `script/build/build_l4.py`（G6：常量追加 + 分支插入 + 序列化回写，**纯字节，无需 Lua 编译器**）；原理见 [restoration-route.md](restoration-route.md) §4.1 |
