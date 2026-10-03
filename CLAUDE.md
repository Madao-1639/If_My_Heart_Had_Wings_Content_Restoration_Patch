# 在这苍穹展翅 内容恢复补丁项目

## 项目目的

为 Steam 版游戏《在这苍穹展翅》（If My Heart Had Wings）制作内容恢复补丁，恢复被 Steam 版删除的原版内容，同时：

1. 保留 Steam 成就系统
2. 恢复完整被删内容
3. 零破坏性修改（不替换 Steam 原有资源）

## 项目背景

### 已确认的技术挑战

- **同名不同内容冲突**：Steam 版与原版部分同名图片资源内容不同（已用 SHA256 验证），不能假设同名文件内容相同
- **内容删减不止表现为文件缺失**：除了 5 个脚本文件被完全移除外，至少 10 个仍存在的脚本文件内部被原地删减了大段对白，脚本首尾跳转结构未变——仅比较文件是否存在会严重低估删减范围
- **成就触发点与内容显示耦合**：Steam 版在几乎每一处 CG 显示指令后都插入了成就调用（已验证覆盖率 100%），还原内容时不能整体替换脚本，必须原样保留这些触发指令及其成就 id（见[工程约定 §9](CLAUDE.md)）

以上均为直接对比 Steam 版归档（`backup/`）与原版发行版归档得出的实测结论，详见 `doc/` 目录。

## 素材来源

- Steam 版基线（只读参考）：`backup/`
- 原版发行版素材：见 `doc/restoration-targets.md` 中记录的路径
- 第三方补丁参考：见 `doc/restoration-targets.md`

## 工程约定

### 1. 文档同步要求

**任何大型修改都必须同步到文档中**

- 修改脚本改写逻辑 → 更新 `doc/file-formats.md`
- 新增资源命名规则 → 更新 `doc/pna-resources.md`
- 修改调用链结构 → 更新 `doc/call-chain.md`
- 发现新问题/解决方案 → 更新 `doc/lessons-learned.md`
- 修改验收标准 → 更新 `doc/acceptance-criteria.md`
- 确认新的还原范围 → 更新 `doc/restoration-targets.md`
- 修改还原技术方案 → 更新 `doc/restoration-route.md`
- 修改交付形态、打包或安装流程 → 更新 `doc/restoration-route.md` §4（流水线与发布链）与本文 §3「测试与发布流程」
- 修改后日谈机制或改动点 → 更新 `doc/afterstory-mechanics.md`
- 修改引擎机制认知（如磁盘裸 `RIO/` 的覆盖语义、`LAYER_ORDER` 行为） → 更新 `doc/engine-mechanics.md`

**文档写法**：只写**最新结论、工作范围、目标、标准/方针/原则、分层与工程约定**；**不写过程叙述**（逐轮进展、发现经过、"推进到 N 批"、实测方法与分歧裁决过程）。过程证据与逐轮记录一律放 `tmp/`（草稿区，不提交）。唯一例外是 `doc/lessons-learned.md`——它就是"问题记录"的指定位置。

文档中标注了状态图例（✅ 已确认 / ⚠️ 部分确认 / ❓ 未知），修改前应先确认相关内容的当前状态，已确认的事实可直接使用，未确认的假设需要先验证再依赖。

### 2. 临时文件管理

**生成的临时文件存放在 `tmp/` 目录下，任务结束后清除**

临时文件包括但不限于：解码后的 WS2 脚本、提取的资源文件、中间处理结果、调试输出文件、一次性使用的工具脚本。

**清理原则**：

- 任务完成后立即清理 `tmp/` 目录
- 重要的中间结果应移动到 `releases/` 或其他持久化目录
- 不将临时文件提交到版本控制

**脚本存放规则**：

- **长期复用的工具**：放入 `tool/`（如 `arcbuild.py`、`ws2.py`、`pna.py`）
- **项目流程脚本**：放入 `script/`
- **一次性/临时脚本**：放入 `tmp/`（任务结束后删除）

### 3. 测试与发布流程

**测试阶段**：`asset/` 只含相对 `backup/` **有差异**的交付文件（无差异归档不进这里，测试时沿用游戏目录里 Steam 自带的那份）；测试时直接把 `asset/` 下的文件覆盖到游戏目录。

**发布阶段**：从 `asset/` 生成增量补丁到 `payload/`，三种交付形态＝**整档覆盖**（打包侧 `OVERWRITE` 名单里体量小的归档 + 玩家目录原本不存在的新档，补丁档与交付路径同名）、**资源级合并**（其余归档按成员表重组玩家原档）、**裸文件**（`RIO/`）；制作安装器打包 `payload/` 内容。

**原则**：开发和测试使用完整文件（`asset/`），发布时才制作增量包（`payload/`）。

### 4. 脚本开发规范

**幂等性**：所有工具脚本必须支持重复运行；运行前检查"已满足则跳过"；不因重复运行产生错误结果。

**回读校验**：改写资源引用后必须回读验证；修改偏移指针后必须验证指向正确；生成归档后必须验证成员完整性（`tool/arcbuild.verify()`）。

**编码规范**：

- 归档成员名、脚本内资源名/对白：Shift-JIS 或 UTF-16LE（视具体字段，见 `doc/file-formats.md`）
- 控制台输出使用 ASCII，或对 stdout 做 UTF-8 reconfigure；解码出的日文/中文文本不要直接 print，先写入 UTF-8 文件再用文件查看工具核对（见 `doc/lessons-learned.md` §1、§7）
- 使用 NUL 前缀的精确替换模式改写脚本内的资源引用，不要用朴素字符串替换

### 5. 验收流程

每次重大修改后按 `doc/acceptance-criteria.md` 执行验收：归档完整性、调用链完整性、成就触发点完整性、资源配对正确性、零破坏性修改核实、实机测试。

### 6. 备份策略

重要修改前必须备份归档（如 `X.arc.before_xxx`），记录备份时间和修改原因，验证备份文件完整性。

### 7. 版本控制

**不提交的文件**：`tmp/` 目录下的所有文件、备份文件（`*.before_*`）、临时输出文件（见 `.gitignore`）。

**必须提交的文件**：所有 Python 脚本、文档文件（`README.md` 和 `doc/` 下所有文件）、配置文件。

**发布链的入库边界**：二进制交付物（`asset/`、`payload/` 里的归档与裸脚本、`releases/` 安装器）**不进版本库**，一律由脚本按 `backup/` + `resource/` + 原版目录重建；安装器要可在版本库里复原，最小集合是 `VERSION`（版本号唯一来源，`script/pack.sh` 与 `tool/install.py` 都读它）、`resource/icon.ico`（安装包图标）、`payload/METADATA.json`（交付成员表与校验和，发布内容的唯一可读记录，也是可复现性闸比对的产物指纹）。

### 8. 安全要求

- 不修改 Steam 原版文件（仅读取用于对比），`backup/` 目录全程只读
- 验证所有输入文件的完整性
- 谨慎处理用户路径输入

## 技术栈

- **语言**：Python
- **编码**：Shift-JIS/UTF-16LE（游戏文件）、UTF-8（文档）
- **归档格式**：自定义 Arc 格式（8 字节头部 + 条目表，详见 `doc/file-formats.md`）
- **脚本格式**：WS2 二进制格式（rotate-6 混淆，详见 `doc/file-formats.md`）
- **资源格式**：PNA（图层容器）、PNG（背景/CG/立绘）、OGG（语音/音效/音乐）、Lua（引擎 UI 逻辑）

## 参考文档

- [README.md](README.md) - 项目概述
- [doc/file-formats.md](doc/file-formats.md) - 文件格式规范
- [doc/engine-mechanics.md](doc/engine-mechanics.md) - 引擎运行时机制
- [doc/afterstory-mechanics.md](doc/afterstory-mechanics.md) - 后日谈机制
- [doc/pna-resources.md](doc/pna-resources.md) - PNA 图层资源与命名规则
- [doc/call-chain.md](doc/call-chain.md) - 调用链组织
- [doc/restoration-targets.md](doc/restoration-targets.md) - 还原目标、范围分层、判定标准与工作范围
- [doc/restoration-route.md](doc/restoration-route.md) - 还原路线、差分标准、流水线与验收
- [doc/script-text-extraction.md](doc/script-text-extraction.md) - 脚本文本提取与民汉译文匹配
- [doc/sem-review-protocol.md](doc/sem-review-protocol.md) - 全量逐行通读的评审判据与交付格式
- [doc/lessons-learned.md](doc/lessons-learned.md) - 问题记录
- [doc/acceptance-criteria.md](doc/acceptance-criteria.md) - 验收标准
