"""将中文译文嵌入到原版脚本中，替换日文原文。

工作流程：
1. 从原版脚本提取对话行（日文原文）
2. 对日文原文计算 CRC32，在 oozora_CHSpatch 翻译表中查找中文译文
3. 将匹配的中文译文直接替换脚本中的日文文本
4. 重新编码生成新的 .ws2 脚本

这样生成的脚本可以：
- 在不依赖 AdvPatch.dll Hook 的情况下直接显示中文
- 保留 Steam 成就系统（通过注入成就调用）
- 适用于 Steam 版引擎
"""
import re
import struct
import json
import zlib
from pathlib import Path
import sys
sys.path.append('..')
from tool import ws2, arcbuild


def calc_crc32_for_translation(text_sjis):
    """计算 CRC32，与 oozora_CHSpatch 算法一致。

    参数:
        text_sjis: Shift-JIS 编码的字节流

    返回:
        有符号 int32 CRC32 值

    必须用 cp932（Windows codepage 932，引擎调用
    `MultiByteToWideChar(932, ...)` 时用的编码），不能用 Python 的
    `shift_jis`——两者在少数字符上不同（如波浪号 U+301C vs U+FF5E），
    详见 ../oozora_CHSpatch/fanchn-crc32-matching-issue.md §3.7。
    """
    # 转为 UTF-16LE
    try:
        text_utf16le = text_sjis.decode('cp932').encode('utf-16le')
    except Exception:
        return None

    # 计算 CRC32
    crc_unsigned = zlib.crc32(text_utf16le) & 0xffffffff
    if crc_unsigned >= 0x80000000:
        return crc_unsigned - 0x100000000
    return crc_unsigned


def load_translation_table(jsonl_path):
    """加载 oozora_CHSpatch 翻译表。

    返回:
        dict: {crc32: chinese_text}
    """
    table = {}
    with open(jsonl_path, 'r', encoding='utf-8') as f:
        for line in f:
            entry = json.loads(line)
            table[entry['crc32']] = entry['text']
    return table


def replace_dialogue_in_script(ws2_data, translation_table):
    """将脚本中的日文对白（和角色名标记）替换为中文译文。

    参数:
        ws2_data: 原始 .ws2 文件数据（已编码）
        translation_table: {crc32: chinese_text} 翻译表

    返回:
        (new_ws2_data, stats): 新的 .ws2 数据和统计信息

    引擎对角色名标记和对话正文分别单独计算 CRC32（不会拼接成一整行），
    已实测验证：角色名标记（`%LC<角色名>`）单独查表命中率 100%，"角色名前缀+
    对话正文"拼接后查表几乎从不命中，详见
    ../oozora_CHSpatch/fanchn-crc32-matching-issue.md §3.7。因此本函数分别
    替换两类标记各自对应的字节范围，不再拼接匹配；角色名标记也一并替换，
    否则替换后的脚本会呈现"日文角色名 + 中文对白"的混合结果。
    """
    decoded = ws2.decode(ws2_data)

    # 角色名标记：\x15 %LC <Shift-JIS角色名> \x00
    CHAR_NAME_PATTERN = re.compile(rb'\x15(%LC[\x80-\xff\x20-\x7f]+?)\x00', re.DOTALL)

    # 对话行：\x14 <idx:u16> <flag:u16> char\x00 <Shift-JIS对白> %P
    # 必须匹配到 %P（文本框结束）而不是第一个 %K（仅换行等待）——原因见
    # extract_script_text.py 顶部注释。
    DIALOGUE_PATTERN = re.compile(
        rb'\x14(.{2})(.{2})char\x00([\x80-\xff\x00-\x7f]+?%P)',
        re.DOTALL
    )

    stats = {
        'total': 0,
        'matched': 0,
        'replaced': 0,
        'failed': 0
    }

    # 收集所有待替换的 (起始偏移, 结束偏移, 原始字节) 三元组，角色名标记和
    # 对话正文混在一起按位置排序后统一替换，避免各自独立累积 offset_delta
    # 导致互相干扰。
    replacements = []

    for match in CHAR_NAME_PATTERN.finditer(decoded):
        stats['total'] += 1
        name_tag_sjis = match.group(1)  # 完整 "%LC<角色名>"

        crc32 = calc_crc32_for_translation(name_tag_sjis)
        chinese_text = translation_table.get(crc32) if crc32 is not None else None
        if chinese_text is None:
            continue
        stats['matched'] += 1

        try:
            chinese_sjis = chinese_text.encode('cp932')
        except Exception:
            stats['failed'] += 1
            continue

        replacements.append((match.start(1), match.end(1), chinese_sjis))

    for match in DIALOGUE_PATTERN.finditer(decoded):
        stats['total'] += 1
        dialogue_text = match.group(3)  # 纯对白文本（包含 %K/%P）

        crc32 = calc_crc32_for_translation(dialogue_text)
        chinese_text = translation_table.get(crc32) if crc32 is not None else None
        if chinese_text is None:
            continue
        stats['matched'] += 1

        try:
            chinese_sjis = chinese_text.encode('cp932')
        except Exception:
            stats['failed'] += 1
            continue

        replacements.append((match.start(3), match.end(3), chinese_sjis))

    # 按起始偏移排序，依次替换并累积偏移变化
    replacements.sort(key=lambda r: r[0])

    result = bytearray(decoded)
    offset_delta = 0
    for text_start, text_end, chinese_sjis in replacements:
        start = text_start + offset_delta
        end = text_end + offset_delta
        old_len = end - start
        new_len = len(chinese_sjis)

        result[start:end] = chinese_sjis
        offset_delta += new_len - old_len

        stats['replaced'] += 1

    return ws2.encode(bytes(result)), stats


def batch_embed_translations(input_arc, translation_jsonl, output_arc):
    """批量处理归档中的所有脚本，嵌入中文译文。

    参数:
        input_arc: 原版 Rio.arc 路径
        translation_jsonl: oozora_CHSpatch 翻译表路径
        output_arc: 输出 Rio.arc 路径
    """
    # 加载翻译表
    print(f"加载翻译表: {translation_jsonl}")
    translation_table = load_translation_table(translation_jsonl)
    print(f"  共 {len(translation_table)} 条译文")
    print()

    # 读取原版归档
    print(f"读取原版归档: {input_arc}")
    members = arcbuild.read_raw(input_arc)
    print(f"  共 {len(members)} 个文件")
    print()

    # 处理每个脚本
    print("嵌入中文译文:")
    new_members = []
    total_stats = {'total': 0, 'matched': 0, 'replaced': 0, 'failed': 0}

    for name_bytes, data in members:
        try:
            name = name_bytes.decode('utf-16le')
        except Exception:
            new_members.append((name_bytes, data))
            continue

        if not name.lower().endswith('.ws2'):
            new_members.append((name_bytes, data))
            continue

        # 替换对白
        new_data, stats = replace_dialogue_in_script(data, translation_table)
        new_members.append((name_bytes, new_data))

        # 更新统计
        for key in total_stats:
            total_stats[key] += stats[key]

        if stats['total'] > 0:
            print(f"  {name}: {stats['replaced']}/{stats['total']} 已替换 "
                  f"({100*stats['replaced']/stats['total']:.1f}%)")

    # 写入新归档
    print()
    print(f"写入新归档: {output_arc}")
    arcbuild.write_arc(new_members, output_arc)

    print()
    print("总计:")
    print(f"  对白总数: {total_stats['total']}")
    print(f"  已匹配: {total_stats['matched']} ({100*total_stats['matched']/total_stats['total']:.1f}%)")
    print(f"  已替换: {total_stats['replaced']} ({100*total_stats['replaced']/total_stats['total']:.1f}%)")
    print(f"  替换失败: {total_stats['failed']}")


if __name__ == '__main__':
    import sys

    if len(sys.argv) < 4:
        print("用法:")
        print("  python -m tool.embed_translations <原版Rio.arc> <翻译表JSONL> <输出Rio.arc>")
        print()
        print("示例:")
        print("  python -m tool.embed_translations \\")
        print("    ../在这片天空下展开一双翅膀(羽翼汉化版V1.0beta2)/Rio.arc \\")
        print("    ../oozora_CHSpatch/release/extracted_text.jsonl \\")
        print("    output/Rio_cn.arc")
        sys.exit(1)

    input_arc = sys.argv[1]
    translation_jsonl = sys.argv[2]
    output_arc = sys.argv[3]

    batch_embed_translations(input_arc, translation_jsonl, output_arc)
