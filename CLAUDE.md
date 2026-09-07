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
- **成就系统与内容显示耦合**：Steam 版在几乎每一处 CG 显示指令后都插入了成就调用（已验证覆盖率 100%），还原内容时必须理解这一耦合关系，不能简单整体替换脚本

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

**测试阶段**：只关注 `asset/` 目录下的文件，测试时直接将 `asset/` 下的文件覆盖到游戏目录。

**发布阶段**：从 `asset/` 生成增量补丁到 `payload/`，制作安装器打包 `payload/` 内容。

**原则**：开发和测试使用完整文件（`asset/`），发布时才制作增量包（`payload/`）。

### 4. 脚本开发规范

**幂等性**：所有工具脚本必须支持重复运行；运行前检查"已满足则跳过"；不因重复运行产生错误结果。

**回读校验**：改写资源引用后必须回读验证；修改偏移指针后必须验证指向正确；生成归档后必须验证成员完整性（`tool/arcbuild.verify()`）。

**编码规范**：
- 归档成员名、脚本内资源名/对白：Shift-JIS 或 UTF-16LE（视具体字段，见 `doc/file-formats.md`）
- 控制台输出使用 ASCII，或对 stdout 做 UTF-8 reconfigure；解码出的日文/中文文本不要直接 print，先写入 UTF-8 文件再用文件查看工具核对（见 `doc/lessons-learned.md` §1、§7）
- 使用 NUL 前缀的精确替换模式改写脚本内的资源引用，不要用朴素字符串替换

### 5. 验收流程

每次重大修改后按 `doc/acceptance-criteria.md` 执行验收：归档完整性、调用链完整性、成就系统完整性、资源配对正确性、零破坏性修改核实、实机测试。

### 6. 备份策略

重要修改前必须备份归档（如 `X.arc.before_xxx`），记录备份时间和修改原因，验证备份文件完整性。

### 7. 版本控制

**不提交的文件**：`tmp/` 目录下的所有文件、备份文件（`*.before_*`）、临时输出文件（见 `.gitignore`）。

**必须提交的文件**：所有 Python 脚本、文档文件（`README.md` 和 `doc/` 下所有文件）、配置文件。

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
- [doc/pna-resources.md](doc/pna-resources.md) - PNA 图层资源与命名规则
- [doc/call-chain.md](doc/call-chain.md) - 调用链组织
- [doc/restoration-targets.md](doc/restoration-targets.md) - 还原目标与素材来源
- [doc/script-text-extraction.md](doc/script-text-extraction.md) - 脚本文本提取与民汉译文匹配验证
- [doc/lessons-learned.md](doc/lessons-learned.md) - 问题记录
- [doc/acceptance-criteria.md](doc/acceptance-criteria.md) - 验收标准
