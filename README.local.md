# 在这苍穹展翅 内容恢复补丁

为 Steam 版《在这苍穹展翅》（If My Heart Had Wings）制作的内容恢复补丁，目标是恢复被 Steam 版删除的原版内容，同时保留 Steam 成就系统，且不破坏 Steam 原有资源。

## 当前状态

项目处于文档与工具搭建阶段。已完成：
- 确认游戏文件格式（Arc 归档、WS2 脚本、PNA 图层容器）
- 确认 Steam 版与原版的具体删减范围（脚本层面与图形资源层面）
- 定位并理解成就系统的注入机制
- 搭建可直接使用的工具库（`tool/arcbuild.py`、`tool/ws2.py`、`tool/pna.py`），均已对真实游戏文件验证字节级正确性

尚未开始实际的内容还原修改工作。详见 [doc/restoration-targets.md](doc/restoration-targets.md) 的待办清单。

## 目录结构

```
tool/       长期复用的工具库（Arc 读写、WS2 编解码、PNA 图层解析）
doc/        项目文档
backup/     Steam 版官方文件，只读参考基线，不可修改
```

## 文档索引

- [doc/file-formats.md](doc/file-formats.md) - 文件格式规范
- [doc/script-text-extraction.md](doc/script-text-extraction.md) - 脚本文本提取与民汉译文匹配验证
- [doc/engine-mechanics.md](doc/engine-mechanics.md) - 引擎运行时机制
- [doc/pna-resources.md](doc/pna-resources.md) - PNA 图层资源与命名规则
- [doc/call-chain.md](doc/call-chain.md) - 调用链组织
- [doc/restoration-targets.md](doc/restoration-targets.md) - 还原目标与素材来源
- [doc/lessons-learned.md](doc/lessons-learned.md) - 问题记录
- [doc/acceptance-criteria.md](doc/acceptance-criteria.md) - 验收标准

## 工程约定

详见 [CLAUDE.md](CLAUDE.md)。
