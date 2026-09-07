"""生成中文 lng 文件，供 Steam 版引擎加载。

工作流程：
1. 从原版脚本提取对话行（日文原文 + lng_idx）
2. 对日文原文计算 CRC32，在 oozora_CHSpatch 翻译表中查找中文译文
3. 按 lng_idx 组织中文译文，生成 lng 文件
4. 使用 XOR 0xCE 加密并编码为 Steam lng 格式

引擎行为：
- 优先查找 lng[idx]，找到则显示 lng 中的译文
- 找不到则回退显示脚本内嵌的日文原文
"""
import json
import struct
import zlib
from pathlib import Path
import sys
from pathlib import Path
tool_path = str(Path(__file__).parent.parent / 'tool')
sys.path.append(tool_path)

# 导入 lng 模块
import lng as lng_codec

# 导入 arcbuild 模块
import arcbuild


def calc_crc32_for_translation(text_sjis):
    """计算 CRC32，与 oozora_CHSpatch 算法一致。

    引擎调用 `MultiByteToWideChar(932, ...)` 转换脚本文本（932 = Windows
    codepage cp932），不是 Python 的 `shift_jis` 编码——两者在少数字符上不同
    （典型例子：波浪号 U+301C，`shift_jis` 解码得到，但 cp932 会解码成全角
    波浪号 U+FF5E）。用错编码会导致含这些字符的整行计算出错误的 CRC32，
    详见 ../oozora_CHSpatch/fanchn-crc32-matching-issue.md §3.7。
    """
    try:
        text_utf16le = text_sjis.decode('cp932').encode('utf-16le')
    except Exception:
        return None

    crc_unsigned = zlib.crc32(text_utf16le) & 0xffffffff
    if crc_unsigned >= 0x80000000:
        return crc_unsigned - 0x100000000
    return crc_unsigned


def load_translation_table(jsonl_path):
    """加载 oozora_CHSpatch 翻译表。"""
    table = {}
    with open(jsonl_path, 'r', encoding='utf-8') as f:
        for line in f:
            entry = json.loads(line)
            table[entry['crc32']] = entry['text']
    return table


def generate_lng_from_script(script_texts, translation_table):
    """从脚本文本生成 lng 文件内容。

    参数:
        script_texts: extract_script_text.py 输出的文本列表
        translation_table: {crc32: chinese_text} 翻译表

    返回:
        list of str: 按 lng_idx 索引的中文译文列表（未匹配的为空字符串）

    引擎对角色名标记和对话正文分别单独计算 CRC32（不会拼接成一整行），
    已实测验证：角色名标记单独查表命中率 100%，"角色名前缀+对话正文"拼接
    后查表几乎从不命中（详见 ../oozora_CHSpatch/fanchn-crc32-matching-issue.md
    §3.7）。因此这里只用去掉角色名前缀后的纯对话正文去查表，不再尝试
    拼接前缀的候选版本。

    去掉前缀时使用 `entry['char_name']` 字段做精确长度剥除，而不是"找第一个
    引号"的启发式——旁白文本可能带角色名前缀却不含任何引号（例如
    "%LC一同みんなの拍手と歓声が、ガレージ内に響き渡った。%K"，角色名"一同"
    后直接是叙述文本，没有「」),用引号启发式会完全剥不掉前缀导致必然不命中。
    """
    import re

    # 找出最大的 lng_idx
    max_idx = max(t['lng_idx'] for t in script_texts)

    # 初始化 lng 数组（用空字符串填充）
    lng_texts = [''] * (max_idx + 1)

    stats = {'total': 0, 'matched': 0, 'failed': 0}

    # 角色名标记模式（仅用于清理译文表中意外带前缀的条目，兜底用）
    CHAR_NAME_PATTERN = re.compile(r'%LC([一-鿿぀-ゟ゠-ヿ]+)')

    for entry in script_texts:
        lng_idx = entry['lng_idx']
        jp_text = entry['text']
        char_name = entry.get('char_name')
        stats['total'] += 1

        # 去掉角色名前缀，得到纯对话正文（引擎单独对这部分计算 CRC32）
        dialogue_only = jp_text
        if char_name:
            expected_prefix = '%LC' + char_name
            if dialogue_only.startswith(expected_prefix):
                dialogue_only = dialogue_only[len(expected_prefix):]

        try:
            # 必须用 cp932 编码：dialogue_only 来自 extract_script_text.py 用
            # cp932 解码的结果（可能含 U+FF5E 全角波浪号等字符），Python 的
            # shift_jis 编码器无法编码这些字符，会直接抛异常。
            jp_sjis = dialogue_only.encode('cp932')
        except Exception:
            continue

        crc32 = calc_crc32_for_translation(jp_sjis)
        chinese_text = translation_table.get(crc32) if crc32 is not None else None

        if chinese_text is None:
            continue

        stats['matched'] += 1

        # 清理中文译文（兜底：万一命中的表项本身仍带角色名前缀）
        cleaned_text = chinese_text
        if cleaned_text.startswith('%LC'):
            match = CHAR_NAME_PATTERN.match(cleaned_text)
            if match:
                cleaned_text = cleaned_text[len(match.group(0)):]

        # 去掉结尾的 %K/%P 控制标记（按后缀匹配，不用 rstrip 避免误删正文末尾字符）
        for suffix in ('%K%P', '%K', '%P'):
            if cleaned_text.endswith(suffix):
                cleaned_text = cleaned_text[:-len(suffix)]
                break

        lng_texts[lng_idx] = cleaned_text

    return lng_texts, stats


def batch_generate_lng_files(script_texts_dir, translation_jsonl, output_dir):
    """批量生成所有脚本的 lng 文件。

    参数:
        script_texts_dir: extract_script_text.py 的输出目录
        translation_jsonl: oozora_CHSpatch 翻译表路径
        output_dir: 输出目录
    """
    script_texts_dir = Path(script_texts_dir)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # 加载翻译表
    print(f"加载翻译表: {translation_jsonl}")
    translation_table = load_translation_table(translation_jsonl)
    print(f"  共 {len(translation_table)} 条译文")
    print()

    print("生成 lng 文件:")

    total_stats = {'total': 0, 'matched': 0, 'failed': 0}
    generated_count = 0

    # 遍历所有脚本文本文件
    for script_file in sorted(script_texts_dir.glob('*.json')):
        script_name = script_file.stem

        # 读取脚本文本
        with open(script_file, 'r', encoding='utf-8') as f:
            data = json.load(f)

        # 生成 lng 内容
        lng_texts, stats = generate_lng_from_script(data['texts'], translation_table)

        # 更新统计
        for key in total_stats:
            total_stats[key] += stats[key]

        # 如果有匹配的译文，则生成 lng 文件
        if stats['matched'] > 0:
            # 编码为 lng 格式
            lng_data = lng_codec.encode_lng(lng_texts)

            # 保存
            output_path = output_dir / f"{script_name}.lng"
            with open(output_path, 'wb') as f:
                f.write(lng_data)

            generated_count += 1
            print(f"  {script_name}.lng: {stats['matched']}/{stats['total']} 已匹配 "
                  f"({100*stats['matched']/stats['total']:.1f}%), {len(lng_data)} bytes")

    print()
    print("总计:")
    print(f"  脚本数: {generated_count}")
    print(f"  对白总数: {total_stats['total']}")
    print(f"  已匹配: {total_stats['matched']} ({100*total_stats['matched']/total_stats['total']:.1f}%)")
    print(f"  未匹配: {total_stats['total'] - total_stats['matched']}")


def pack_lng_to_arc(lng_dir, output_arc):
    """将 lng 文件打包成 Rio.arc。

    参数:
        lng_dir: lng 文件目录
        output_arc: 输出 Rio.arc 路径
    """
    lng_dir = Path(lng_dir)

    print(f"打包 lng 文件到归档: {output_arc}")

    members = []
    for lng_file in sorted(lng_dir.glob('*.lng')):
        name = lng_file.name
        name_bytes = name.encode('utf-16le') + b'\x00\x00'
        data = lng_file.read_bytes()
        members.append((name_bytes, data))

    arcbuild.write_arc(members, output_arc)
    print(f"  共 {len(members)} 个文件")


if __name__ == '__main__':
    import sys

    if len(sys.argv) < 4:
        print("用法:")
        print("  python -m tool.generate_lng <脚本文本目录> <翻译表JSONL> <输出目录> [--pack <输出arc>]")
        print()
        print("示例:")
        print("  # 生成 lng 文件")
        print("  python -m tool.generate_lng \\")
        print("    tmp/script_texts \\")
        print("    ../oozora_CHSpatch/release/extracted_text.jsonl \\")
        print("    output/lng")
        print()
        print("  # 生成并打包为 arc")
        print("  python -m tool.generate_lng \\")
        print("    tmp/script_texts \\")
        print("    ../oozora_CHSpatch/release/extracted_text.jsonl \\")
        print("    output/lng \\")
        print("    --pack output/Rio_cn.arc")
        sys.exit(1)

    script_texts_dir = sys.argv[1]
    translation_jsonl = sys.argv[2]
    output_dir = sys.argv[3]

    batch_generate_lng_files(script_texts_dir, translation_jsonl, output_dir)

    # 如果指定了 --pack，则打包为 arc
    if len(sys.argv) >= 6 and sys.argv[4] == '--pack':
        output_arc = sys.argv[5]
        print()
        pack_lng_to_arc(output_dir, output_arc)
