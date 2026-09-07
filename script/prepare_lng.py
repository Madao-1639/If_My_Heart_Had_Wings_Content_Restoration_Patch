"""为内容恢复补丁准备中文 lng 文件。

策略：
1. 从 Steam 中文版直接复制已有的 lng 文件（95 个脚本，质量最高）
2. 为被删除的 5 个脚本生成 lng 框架（使用日文原文作为占位符）
3. 输出缺失译文的清单，供后续补充

这样可以：
- 最大化利用 Steam 官方中文翻译（72% 已覆盖）
- 为恢复的内容提供统一的 lng 接口
- 明确标识需要补充翻译的部分
"""
import json
from pathlib import Path
import sys
from pathlib import Path
tool_path = str(Path(__file__).parent.parent / 'tool')
sys.path.append(tool_path)

# 导入 lng 模块
import lng as lng_codec

# 导入 arcbuild 模块
import arcbuild


def copy_steam_lng_files(steam_arc, output_dir):
    """从 Steam 中文版复制 lng 文件。

    返回:
        set: 已复制的脚本名集合
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    print(f"从 Steam 中文版复制 lng 文件: {steam_arc}")
    members = arcbuild.read_raw(steam_arc)

    copied = set()
    for name_bytes, data in members:
        try:
            name = name_bytes.decode('utf-16le')
        except Exception:
            continue

        if not name.lower().endswith('.lng'):
            continue

        script_name = Path(name).stem
        output_path = output_dir / name
        output_path.write_bytes(data)

        copied.add(script_name)
        print(f"  {name}: {len(data)} bytes")

    return copied


def generate_placeholder_lng(script_texts, output_path):
    """为缺失的脚本生成占位符 lng 文件（使用日文原文）。

    参数:
        script_texts: extract_script_text.py 输出的文本列表
        output_path: 输出 lng 文件路径

    返回:
        int: 条目数
    """
    # 找出最大的 lng_idx
    max_idx = max(t['lng_idx'] for t in script_texts)

    # 初始化 lng 数组（用空字符串填充）
    lng_texts = [''] * (max_idx + 1)

    # 填充日文原文（去掉控制标记）
    for entry in script_texts:
        lng_idx = entry['lng_idx']
        jp_text = entry['text']

        # 去掉 %LC 前缀和 %K/%P 后缀
        cleaned = jp_text
        if cleaned.startswith('%LC'):
            # 找到第一个「或"
            for i, ch in enumerate(cleaned):
                if ch in '「『"':
                    cleaned = cleaned[i:]
                    break

        cleaned = cleaned.rstrip('%K').rstrip('%P')
        lng_texts[lng_idx] = cleaned

    # 编码并保存
    lng_data = lng_codec.encode_lng(lng_texts)
    output_path.write_bytes(lng_data)

    return len(script_texts)


def prepare_lng_for_restoration(script_texts_dir, steam_arc, output_dir):
    """准备内容恢复补丁所需的 lng 文件。

    参数:
        script_texts_dir: extract_script_text.py 的输出目录
        steam_arc: Steam 中文版 Rio.arc 路径
        output_dir: 输出目录
    """
    script_texts_dir = Path(script_texts_dir)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # 1. 复制 Steam 中文版 lng
    print("=" * 60)
    copied_scripts = copy_steam_lng_files(steam_arc, output_dir)
    print(f"\n已复制: {len(copied_scripts)} 个 lng 文件")

    # 2. 为缺失的脚本生成占位符 lng
    print("\n" + "=" * 60)
    print("为被删除的脚本生成占位符 lng:")

    missing_scripts = []
    for script_file in sorted(script_texts_dir.glob('*.json')):
        script_name = script_file.stem

        if script_name in copied_scripts:
            continue

        # 读取脚本文本
        with open(script_file, 'r', encoding='utf-8') as f:
            data = json.load(f)

        # 生成占位符 lng
        output_path = output_dir / f"{script_name}.lng"
        count = generate_placeholder_lng(data['texts'], output_path)

        missing_scripts.append({
            'script': script_name,
            'count': count,
            'size': output_path.stat().st_size
        })

        print(f"  {script_name}.lng: {count} 条日文原文, {output_path.stat().st_size} bytes")

    # 3. 生成缺失译文清单
    if missing_scripts:
        print("\n" + "=" * 60)
        print("生成缺失译文清单:")

        manifest_path = output_dir / 'missing_translations.json'
        with open(manifest_path, 'w', encoding='utf-8') as f:
            json.dump({
                'total_scripts': len(missing_scripts),
                'total_entries': sum(s['count'] for s in missing_scripts),
                'scripts': missing_scripts,
                'note': '这些脚本的 lng 文件当前使用日文原文作为占位符，需要补充中文翻译'
            }, f, ensure_ascii=False, indent=2)

        print(f"  {manifest_path}")
        print(f"\n  需要补充翻译的脚本: {len(missing_scripts)} 个")
        print(f"  需要补充翻译的条目: {sum(s['count'] for s in missing_scripts)} 条")

    # 4. 总结
    print("\n" + "=" * 60)
    print("总结:")
    print(f"  Steam 中文版 lng: {len(copied_scripts)} 个")
    print(f"  占位符 lng: {len(missing_scripts)} 个")
    print(f"  总计: {len(copied_scripts) + len(missing_scripts)} 个 lng 文件")


def pack_lng_to_arc(lng_dir, output_arc):
    """将 lng 文件打包成 Rio.arc。"""
    lng_dir = Path(lng_dir)

    print(f"\n打包 lng 文件到归档: {output_arc}")

    members = []
    for lng_file in sorted(lng_dir.glob('*.lng')):
        name = lng_file.name
        name_bytes = name.encode('utf-16le')
        data = lng_file.read_bytes()
        members.append((name_bytes, data))

    arcbuild.write_arc(members, output_arc)
    print(f"  共 {len(members)} 个文件")


if __name__ == '__main__':
    import sys

    if len(sys.argv) < 4:
        print("用法:")
        print("  python -m tool.prepare_lng <脚本文本目录> <Steam中文Rio.arc> <输出目录> [--pack <输出arc>]")
        print()
        print("示例:")
        print("  # 准备 lng 文件")
        print("  python -m tool.prepare_lng \\")
        print("    tmp/script_texts \\")
        print("    backup/zh-CN/Rio.arc \\")
        print("    output/lng")
        print()
        print("  # 准备并打包为 arc")
        print("  python -m tool.prepare_lng \\")
        print("    tmp/script_texts \\")
        print("    backup/zh-CN/Rio.arc \\")
        print("    output/lng \\")
        print("    --pack output/Rio_cn.arc")
        sys.exit(1)

    script_texts_dir = sys.argv[1]
    steam_arc = sys.argv[2]
    output_dir = sys.argv[3]

    prepare_lng_for_restoration(script_texts_dir, steam_arc, output_dir)

    # 如果指定了 --pack，则打包为 arc
    if len(sys.argv) >= 6 and sys.argv[4] == '--pack':
        output_arc = sys.argv[5]
        pack_lng_to_arc(output_dir, output_arc)
