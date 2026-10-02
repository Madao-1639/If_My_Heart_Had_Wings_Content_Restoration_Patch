# 在这苍穹展翅 内容恢复补丁

为 Steam 版 [《在这苍穹展翅》（If My Heart Had Wings）](https://store.steampowered.com/app/326480/) 还原被移除的剧情内容，同时完整保留 Steam 成就触发点与官方中文本地化（成就本身由开发者与 Steam 共同管理，本补丁不干预），还原文本使用 [羽翼汉化组的汉化文本](https://github.com/jszhtian/oozora_CHSpatch)。

本补丁仅供已购买正版游戏的用户使用，不包含任何游戏本体文件。

![Banner](https://shared.steamstatic.com/store_item_assets/steam/apps/326480/library_hero.jpg?t=1573643772)

## 当前状态

### 文本层 ✅ 已完成并通过验收

羽翼汉化组的对白已逐行映射回**原版**（非 Steam 版）日文脚本，按 idx 组装为逐脚本中文文本 `resource/fan_cn/{SCRIPT}.json`（104 个文件，`idx → 中文文本`），配套 `NameTable.json`（99 条）。引擎装载形态（`.lng`，XOR 0x88，与官方 zh-CN 同格式）+ `NameTable.txt` **不留档**：构建时从 JSON 现做（`tool/fancn.load_texts` → `tool/lng.encode_lng`）并直接封进 `Rio.arc`；`python script/build_fan_translations.py --emit-lng` 只是临时试装出口。复检链一律读 `resource/fan_cn/`（经 `tool/fancn.py`）。

| 项 | 读数 |
|---|---|
| **条目数对账（验收项）** | 日文占槽位行 54,254 → 中文非空槽位 54,253；逐脚本双向差集 **0** |
| 写入-回读 | `readback 54,254 mismatch 0`；`%K`/`%P` 节奏标记与日文逐行同构 |
| 语境层修正 | **3,526** 槽（机械规范化 + 逐槽位语境修正 + 出包门禁 + 只读复检）；唯一载体 `resource/corpus/review_fixes.jsonl`，每行 `from` 记来源层 |
| 复读 | 相邻同文 **0 对**（按 idx 出包从根上消除） |
| 零日文回退 | 漏译就地补译，**不留空回退日文** |
| **全量逐行通读** | **215 批全部交付 / 提案 1,563 条**；落地核对 `batches 215 checked 1,563 mismatch 0`；单薄队列 `thin 0 / sticky 0 / pending 0` |

已纠正的缺陷类（全部固化进**可复跑流水线**，不靠一次性人工编辑）：玩家反馈的五类（复读、译名不统一、繁简混合、漏翻、译校批注残留），以及追加清出的——未翻日文词（`部活`/`寮母`/`日直`…）、专名形近错字（`佳柰子`/`亚沙`）、日式字形与繁体残留、软换行半角缩进、GBK 码页吃掉的符号（`♪`/`・`/`〜`）、同音形近错字、解说式圆括注、落单引号、句读叠用、表地址占位残留、与日文同形的未译职务/亲属词。

可复跑的范围是**出包链路**：`resource/corpus/pairing.jsonl` + `resource/corpus/review_fixes.jsonl` → `resource/fan_cn/` 逐字节可重建。语境修正以改动表为终态留档；产生它的提案批次与人工裁决批次属于过程稿，不进版本库，新一轮改动按槽位增量并入改动表。

方法与验收数据见 [doc/script-text-extraction.md](doc/script-text-extraction.md) §6–§7；评审判据与交付格式见 [doc/sem-review-protocol.md](doc/sem-review-protocol.md)；踩坑记录见 [doc/lessons-learned.md](doc/lessons-learned.md)。

### 内容还原 ⏳ 未开始

范围与路线均已确定（范围按 **L1 H 场景 → L2 出入口差分 → L3 擦边台词 → L4 后日谈 → L5 官方修正差异** 分层；路线为**从 `backup/` 起底构建 `asset/`**）。详见：

- [doc/restoration-targets.md](doc/restoration-targets.md) — 还原目标、范围分层、判定标准与工作范围
- [doc/restoration-route.md](doc/restoration-route.md) — 还原路线：差分标准、构建路线、流水线与验收
- [doc/afterstory-mechanics.md](doc/afterstory-mechanics.md) — 后日谈（After Story）机制与 L4 开发依据
- [doc/engine-mechanics.md](doc/engine-mechanics.md) — 引擎机制（含**「引擎会读取裸 `RIO/` 脚本并覆盖归档」**这条关键结论）

## 目录结构

```
doc/        项目文档
backup/     Steam 版官方文件，只读参考基线，不可修改
tool/       长期复用的工具库（Arc 读写、WS2 编解码、PNA 图层解析、中文文本规范化）
script/     构建和开发脚本
resource/   全部输入表（文本层底稿 corpus/：日文 jp/、民汉旧提取 zh/、行对齐 pairing.jsonl、语境改动表 review_fixes.jsonl；中文文本 fan_cn/、NameTable、承载图、判读台账 adjudication/、改名表、插入计划、成就基线）——逐表字段与读写关系见 resource/README.md
asset/      构建产物（完整文件，测试时直接覆盖游戏目录）—— 从 backup/ 起底生成
payload/    增量补丁（发布用，由 asset/ 生成）
```

## To-Do

**文本层**
- [x] 提取羽翼汉化组的汉化文本
- [x] 按 idx 重建为原版可用的中文文本，并纠正语料五类缺陷
- [x] 全量逐行通读（215 批）

**内容还原**
- [x] 确定还原范围（分层 L1–L5）
- [x] 探明后日谈（After Story）机制与改动点
- [ ] 建承载图 / 改名表 / 插入计划
- [ ] 执行还原
- [ ] 全量测试
- [x] 后日谈
- [ ] 其他细微文本差异