"""If My Heart Had Wings Content Restoration Patch - Tool libraries.

通用库包：
  - arcbuild: Arc 归档读写（成员名保留原始字节）+ `verify()` 完整性校验
  - ws2: WS2 脚本编解码（rotate-left-6）与成就调用注入
  - ws2dis: WS2 线性反汇编（操作数格式表取自引擎自身）
  - ws2conv: 原版 WS2 → Steam WS2 编码转换（本体线与 L4 共用的公共工序）
  - writer: 宿主脚本结构写盘（删格 / 插入 / 名字框恢复）
  - scriptext: 原版脚本的文本行提取
  - lng: `.lng` 中文覆盖层容器编解码
  - pna: `.pna` 图层容器读写
  - fancn: `resource/fan_cn/{SCRIPT}.json` 中文文本的统一读取口径
  - textfix: 中文译文的机械规范化（零判断批量改写）
  - v5lib: 判读共享库（承载图行索引、锚点、资源存在性判据）
  - install: 安装器（发布入口）；其 `merge_arc`／`payload_path_for` 由打包侧
    `script/generate_payload.py` 共用，保证打包与安装同一口径
"""
