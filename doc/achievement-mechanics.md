# 成就系统完整机制（背景文档）

> **定位：本文档是背景资料，不是工程依据。**
>
> - 成就由**游戏开发者与 Steam 共同管理**（成就定义、API 名、显示名、图标、解锁状态都在 Steam 侧），**本补丁无法也不应干预**。
> - 本补丁能操作的只有**触发点**（脚本里的成就指令）。工程依据、处理原则与保留纪律见 [engine-mechanics.md](engine-mechanics.md) §成就触发点契约。
> - 只在需要「核对某条成就指令到底触发了什么」时才查本文档；日常还原工作**只需保证保留指令的字节形态与 id 一致**即可。

> 状态图例：✅ 已确认 / ⚠️ 部分确认 / ❓ 未知
> 基线：Steam `backup/`（只读）；引擎分析基于 **脱壳** `AdvHD.exe.unpacked.exe`（VAdvHD 1.72c `Release - Steam`）。
> 机器可读数据：`resource/achievement_map.json`。

---

## 一、脚本层：CG 显示点与 29 处 `0xF0` ✅

Steam 版每个 CG 显示点的固定结构：

```
0x33 <槽位> <资源名.PNG> <u8> <u8>      ; 显示 CG
0x0b <u16 A> 01                          ; A ∈ 1089…1189：场景/图库分组
0x0b <u16 B> 01                          ; B ∈ 1190…2674：该 CG 编号
0x04 "CG_ACHIEVEMENT" 00                 ; RunFile 成就脚本（16 字节，含 NUL）
```

全库（`Rio.arc` **158 个 `.ws2`**）共 **29 处 `0xF0 <u8 idx>` 指令**（线性解析 153/158；`CG_PAGE10/12`、`CO1_018`、`CO2_005`、`HUT_005` 含内嵌菜单/数据表，无法线性解析，其 `0xF0` 未计入）。分布：`CG_Achievement` 6 处，其余 23 处散落在 17 个剧情/菜单脚本。

`CG_Achievement.ws2` 本身是 **VM 字节码，不是不透明数据表**：

```
头        : 09 00 37 00 00 00 00 00            ; LayerConfig(mode=0, id=55, 0.0) —— 初始化计数器
每条记录  : 01 02 <u16 CG#> 00 00 80 3f        ; Condition(mode=2, id=CG#, val=1.0, b=下一记录)
            00 00 00 00 <u32 下一记录偏移>
            09 01 37 00 00 00 80 3f            ; LayerConfig(mode=1, id=55, 1.0) —— var[55] += 1.0
尾部      : 6 × [ Condition(mode=0x80, id=55, <阈值>, b=下一块) + F0 <u8 idx> ] + 05 + ff + 8 字节尾
```

即：`if var[CG#] == 1.0 then var[55] += 1.0`，再按 `var[55]` 阈值触发 6 个收集类成就。

## 二、引擎层：`0xF0` = 成就触发 ✅

**分发**：`sub_4597A0` 建 VM 分发表（`this+0x1D2C`，256 项 dword），表项 **240（= 0xF0）** 填 `sub_46AC00`（唯一 data xref `0x459d1a`）。

**`sub_46AC00`（handler 0xF0）** 反编译要点：

```c
BYTE idx = sub_458E80(*a5);                     // 取 F0 操作数（VARIANT→BYTE）
if ( idx >= *(DWORD*)(this + 7420) ) return 0;  // 越界 ⇒ 空操作（7420 = LegacyGame+0x1CFC = 成就数）
DWORD off  = 400 * idx;
DWORD base = *(DWORD*)(this + 7436);            // 7436 = LegacyGame+0x1D0C = vector<achievement_t> 数据指针
if ( *(BYTE*)(off+base+392) != 1 ) {            // +0x188 = m_bAchieved（去重）
    *(BYTE*)(off+base+392) = 1;
    *(DWORD*)(off+base+396) = 0;                // +0x18C = m_iIconImage
    ISteamUserStats::vtbl[+0x1C]( ..., *(DWORD*)(off+base+4) );  // SetAchievement( m_pchAchievementID )
    ISteamUserStats::vtbl[+0x28]( ... );                          // StoreStats()
}
```

**成就管理器**（`CStatsAndAchievements` 子对象）= `LegacyGame + 0x1CC0`（构造见 `sub_46BB00` @`0x46c05e`–`0x46c15c`）：

| 偏移 | 内容 |
|---|---|
| `+0x00` | `CCallback<CStatsAndAchievements, UserStatsReceived_t>` vftable |
| `+0x10` | 回调处理函数 = **`sub_4CEDB0`**（`SteamAPI_RegisterCallback(edi, 0x44D)`） |
| `+0x14` | `CCallback<…, UserAchievementStored_t>` vftable（`0x44F` → `byte_4CEFF0`） |
| `+0x28` | AppID（与 `UserStatsReceived_t.m_nGameID` 比对） |
| `+0x30` | `HSteamUser` |
| `+0x34` | **`ISteamUserStats*`**（`STEAMUSERSTATS_INTERFACE_VERSION011`） |
| `+0x38` | 状态已收到标志 |
| `+0x3C` | 成就数（`GetNumAchievements()` 结果） |
| `+0x40` | `vector<std::string>`：成就 API 名（按 `GetAchievementName(i)` 顺序） |
| `+0x4C` | **`vector<achievement_t>`（元素 400 字节）= `F0` 的索引表** |

`ISteamUserStats` vtable 槽位（**offset = 4 × 接口序号**，无析构前缀）：`+0x00` RequestCurrentStats、`+0x18` GetAchievement、`+0x1C` SetAchievement、`+0x28` StoreStats、`+0x30` GetAchievementDisplayAttribute、`+0x38` GetNumAchievements、`+0x3C` GetAchievementName。

`achievement_t`（400 B，Valve SDK 样例同构）：`+0x00` m_eAchievementID、**`+0x04` m_pchAchievementID**（`SetAchievement` 的实参）、`+0x08` name[128]、`+0x88` desc[256]、`+0x188` m_bAchieved、`+0x18C` m_iIconImage。

## 三、成就表在运行时由 Steam 构建 ✅

`sub_4CEDB0`（`UserStatsReceived_t` 回调）在收到 Steam 统计后建表：

```
count = GetNumAchievements();
for i in 0..count-1:
    name = GetAchievementName(i);                                           // → push_back 到 +0x40 向量
    GetAchievement(name, &state);
    vector<achievement_t>::push_back({ i, name,                             // +0x4C
        GetAchievementDisplayAttribute(name, "name"),
        GetAchievementDisplayAttribute(name, "desc"), ... });
```

⇒ **`F0 <idx>` 的 idx = Steam 成就枚举序的 0 基序号**。成就名与显示名**既不在 exe、也不在脚本**（脱壳后 exe 内 `ACHIEVEMENT` 相关字符串仅 3 条：Lua 事件名 + 2 个 RTTI），全部来自 Steam。

## 四、完整映射（0 基 `idx` → 成就）✅ 已逐点核对

成就清单取自 Steam 客户端 schema 缓存 `…/appcache/stats/UserGameStatsSchema_326480.bin`（appid **326480**，共 **20 项**，`IMH_ACHIEVEMENT_01..20`，**文件顺序即枚举顺序**）⇒ **`F0 i` → `IMH_ACHIEVEMENT_(i+1)`**。

| `F0 idx` | API 名 | 显示名 | 触发位置 |
|---|---|---|---|
| 0 | `IMH_ACHIEVEMENT_01` | Welcome（Start the game） | `CO1_001` @0x00000（序章首指令） |
| 1 | `_02` | Movie I | `CO1_010` @0x0877b（紧接 `movie` 播放） |
| 2 | `_03` | Movie II | `CO1_021_B` @0x03e03（紧接 `movie`） |
| 3 | `_04` | Movie III（ending movie） | `AGE_011`/`AMA_009`/`ASA_005`/`KOT_008`/`YOR_008`（各线倒数第二章末尾） |
| 4 | `_05` | Gallery | `mainmenu` @0x0016a（`var127 == 0` → `openGallery`） |
| 5 | `_06` | Never Give Up（common routes） | `CO1_021_B` @0x03e05 |
| 6 | `_07` | Congratulations! | `AGE_012`/`AMA_010`/`ASA_005`/`KOT_009`/`YOR_008`（各线结局） |
| 7 | `_08` | Cool 'Allule'（Kotori） | `KOT_009` @0x1e570 |
| 8 | `_09` | Amane Senpai | `AMA_010` @0x132de |
| 9 | `_10` | Classmates（Ageha） | `AGE_012` @0x04260 |
| 10 | `_11` | Asa Is the Elder Twin Sister | `ASA_005` @0x118d2 |
| 11 | `_12` | Yoru Is the Younger Twin Sister | `YOR_008` @0x1d86a |
| 12 | `_13` | Too Bad!（bad end） | `CO2_999` @0x0260f（`NextFile "TITLE"` 之前） |
| 13 | `_14` | Astonishing!（all routes） | `title` @0x00050（5 个通关 flag 全真后） |
| 14 | `_15` | First Contact | `CG_Achievement`（`var[55] >= 1`） |
| 15 | `_16` | Approach（20%） | `CG_Achievement`（`>= 79`） |
| 16 | `_17` | Take-Off（40%） | `CG_Achievement`（`>= 158`） |
| 17 | `_18` | Soar（60%） | `CG_Achievement`（`>= 237`） |
| 18 | `_19` | Glide（80%） | `CG_Achievement`（`>= 316`） |
| 19 | `_20` | Morning Glory（100%） | `CG_Achievement`（`>= 395`） |
| **28** | — | — | `CG_PAGE09` @0x1ce7：**越界（成就数 = 20）⇒ 空操作**（遗留触发点） |

脚本层的 `0xF0` 扫描可复现：`tool/ws2dis.py --arc <Rio.arc>`（解析率 153/158）。

## 五、为什么还原不需要动它

成就的**数据与触发条件**全在脚本层（`0x0b` 变量对 + `F0 <idx>` + `CG_Achievement.ws2`），引擎只做「按 idx 查运行时表 → 调 `SetAchievement` + `StoreStats`」。

⇒ **只要原样保留 Steam 脚本里的成就指令，成就行为即完整复现**，不需要理解引擎内部实现，也不需要还原 `CG_Achievement.ws2`（Steam 版已含且未被删改）。

## 参考

| 对象 | 路径 |
|---|---|
| 机器可读映射表 | `resource/achievement_map.json`（20 项成就 + 29 处触发点） |
| WS2 反汇编器 | `tool/ws2dis.py` + `tool/ws2fmt.txt` |
| 引擎触发契约（工程依据） | [engine-mechanics.md](engine-mechanics.md) §成就触发点契约 |
| 成就指令在文件格式中的位置 | [file-formats.md](file-formats.md) §成就注入机制 |
