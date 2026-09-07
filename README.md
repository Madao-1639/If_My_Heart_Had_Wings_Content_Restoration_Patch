# 在这苍穹展翅 内容恢复补丁

为 Steam 版 [《在这苍穹展翅》（If My Heart Had Wings）](https://store.steampowered.com/app/326480/) 还原被移除的剧情内容，同时完整保留 Steam 成就系统与官方中文本地化，还原文本使用 [羽翼汉化组的汉化文本](https://github.com/jszhtian/oozora_CHSpatch)。

## 当前状态

项目处于文档与工具搭建阶段。已完成：
- 确认游戏文件格式（Arc 归档、WS2 脚本、PNA 图层容器）
- 确认 Steam 版与原版的具体删减范围（脚本层面与图形资源层面）
- 定位并理解成就系统的注入机制
- 搭建可直接使用的工具库（`tool/arcbuild.py`、`tool/ws2.py`、`tool/pna.py`），均已对真实游戏文件验证字节级正确性

尚未开始实际的内容还原修改工作。详见 [doc/restoration-targets.md](doc/restoration-targets.md) 的待办清单。

## 目录结构

```
doc/        项目文档
backup/     Steam 版官方文件，只读参考基线，不可修改
tool/       长期复用的工具库（Arc 读写、WS2 编解码、PNA 图层解析）
script/     构建和开发脚本
fulltext/   提取的游戏文本
```

## To-Do
- [x] 提取羽翼汉化组的汉化文本
- [ ] 确定还原范围
- [ ] 执行还原
- [ ] 全量测试