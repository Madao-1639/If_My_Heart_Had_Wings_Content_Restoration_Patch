# 验收标准

补丁完成后应满足以下条件才能视为完成。以下标准是每次改动都应遵循的检查清单：**机检项**由 `script/final_verification.py` 逐条断言（闸的编号与次序见 [restoration-route.md](restoration-route.md) §5），**实机项**（见文末「实机测试」）只能手工跑图，不由脚本断言。

## 归档与文件完整性

- [ ] 改写后的 `.arc` 文件通过 `tool/arcbuild.verify()`，无成员越界、无表尾多余 null padding
- [ ] 改写后的 `.ws2` 脚本可正常用 `tool/ws2.decode()` 解码，不抛异常
- [ ] 改写后的 `.pna` 文件可正常用 `tool/pna.load()` 解析，且 `layer_count` 与实际条目数、图层数据边界一致

## 调用链完整性

- [ ] 所有新插入的跳转/调用目标脚本在归档中确实存在
- [ ] 原地插入的还原内容片段之后，脚本原有的其余部分（包括 Steam 版新增的成就调用指令）未被破坏或误删
- [ ] 用脚本扫描全部路线前缀，确认没有遗留指向不存在脚本名的跳转（见 [call-chain.md](call-chain.md)）

## 成就触发点完整性

> 原则：成就由开发者与 Steam 共同管理，本补丁**只保留触发点**（不修改、不新增、不重算 id）。见 `CLAUDE.md` §工程约定 9、[engine-mechanics.md](engine-mechanics.md) §成就触发点契约。
> 基线数据：`resource/achievement_map.json`。

- [ ] 全部 `CG_ACHIEVEMENT` 调用点（基线 **922 处 / 51 脚本**）逐字节保留，未被删除、合并或重排
- [ ] 每个调用点的 `0x0b` 变量对（A = 场景分组、B = CG 编号）取值与基线**逐一对应**，未改写、未重算
- [ ] 全部 `0xF0 <idx>` 触发点（基线 **29 处**）保留，`idx` 取值集合与基线一致；越界点（`CG_PAGE09` 的 `F0 28`）**原样保留**，不得"修正"为合法值
- [ ] 原地插入的还原内容未切断 `0x33 → 0x0b A → 0x0b B → 0x04 "CG_ACHIEVEMENT"` 四连序列
- [ ] **未新增**任何成就触发指令：被删 5 脚本（`ASA_002/004`、`YOR_003/005/007`）内回填的 CG 显示点未补钩子（332 处）
- [ ] `CG_Achievement.ws2` 未被改动

**校验手段**：`tool/ws2dis.py --arc <Rio.arc>` 复扫改造前后，比对 `0xF0` 站点数/`idx` 集合与 `CG_ACHIEVEMENT` 调用数、`0x0b` 变量对取值集合是否不变。

## 资源配对正确性

- [ ] 改动涉及的同名资源已逐一核实 hash，确认是否存在"同名不同内容"冲突（见 [restoration-targets.md](restoration-targets.md) §4）
- [ ] 涉及 PNA 图层替换的操作，已确认 layer_id 对应关系没有因为图层数量变化而错位

## 零破坏性修改

- [ ] Steam 原有资源（未涉及还原范围的部分）未被覆盖或修改
- [ ] `backup/` 目录中的文件全程保持只读，未被任何脚本写入

## 实机测试

- [ ] 每次重大修改后，实际运行游戏测试受影响场景，确认无卡死、无报错、画面显示正常
- [ ] 测试成就触发是否正常（如果游戏支持在非 Steam 环境下模拟触发进行调试）

## 待完善

- **实机场景清单**：见 [restoration-route.md](restoration-route.md) §5 第 7 项（A-1 的 5 个整脚本入口、A-2 插入点前后、后日谈入口链路 `mainmenu` → `start.ws2` → `flag 126` 路由）。
- **安装器在真实玩家目录的交付回归**：机检覆盖到 `payload/` 的重放校验（`script/generate_payload.py` 按安装器同一口径重算并与 `asset/` 逐字节比对），未在一份真实 Steam 装机上跑过整档覆盖／资源级合并／裸文件三类交付与失败恢复路径。
