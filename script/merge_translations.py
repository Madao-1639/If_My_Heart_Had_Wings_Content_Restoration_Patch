"""合并日文原文与 Steam 中文译文。

从原版脚本提取的日文原文（带 lng_idx）+ Steam 中文版 lng 文件（按索引存储）
→ 生成完整的日中对照表
"""
import json
import struct
from pathlib import Path
import sys
sys.path.append('..')
from tool import arcbuild


def parse_lng_xor_ce(raw):
    """解析 lng 文件（XOR 0xCE 解密）。"""
    XOR_CE = bytes(c ^ 0xCE for c in range(256))
    count = struct.unpack_from('<I', raw, 0)[0]
    lens = struct.unpack_from('<%dH' % count, raw, 4)
    off = 4 + 2 * count
    out = []
    for length in lens:
        chunk = raw[off:off + length]
        off += length
        try:
            decrypted = chunk.translate(XOR_CE)
            text = decrypted.decode('utf-16le').rstrip('\x00')
            out.append(text)
        except Exception:
            out.append(None)  # 解码失败返回 None
    return out


def merge_script_translations(japanese_texts, chinese_texts):
    """合并日文原文和中文译文。

    参数:
        japanese_texts: list of {"lng_idx": int, "text": str, "has_char_name": bool}
        chinese_texts: list of str (按 lng_idx 索引)

    返回:
        list of {"lng_idx": int, "japanese": str, "chinese": str, "matched": bool}
    """
    results = []

    for jp_entry in japanese_texts:
        lng_idx = jp_entry['lng_idx']
        jp_text = jp_entry['text']

        # 从 Steam 中文 lng 中查找对应的译文
        if lng_idx < len(chinese_texts) and chinese_texts[lng_idx] is not None:
            cn_text = chinese_texts[lng_idx]
            matched = True
        else:
            cn_text = "[缺失]"
            matched = False

        results.append({
            "lng_idx": lng_idx,
            "japanese": jp_text,
            "chinese": cn_text,
            "has_char_name": jp_entry.get('has_char_name', False),
            "matched": matched
        })

    return results


def batch_merge(japanese_dir, steam_cn_arc, output_dir):
    """批量合并所有脚本的日中译文。

    参数:
        japanese_dir: 日文原文目录（extract_script_text.py 的输出）
        steam_cn_arc: Steam 中文版 Rio.arc 路径
        output_dir: 输出目录
    """
    japanese_dir = Path(japanese_dir)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # 读取 Steam 中文版 lng 文件
    print(f"读取 Steam 中文版归档: {steam_cn_arc}")
    members = arcbuild.read_raw(steam_cn_arc)

    steam_lng = {}
    for name_bytes, data in members:
        try:
            name = name_bytes.decode('utf-16le')
        except Exception:
            continue

        if name.lower().endswith('.lng'):
            script_name = Path(name).stem
            chinese_texts = parse_lng_xor_ce(data)
            steam_lng[script_name] = chinese_texts
            print(f"  {script_name}.lng: {len(chinese_texts)} 条")

    print(f"\n合并日中译文:")

    total_scripts = 0
    total_matched = 0
    total_entries = 0

    # 遍历日文原文文件
    for jp_file in sorted(japanese_dir.glob('*.json')):
        script_name = jp_file.stem

        # 读取日文原文
        with open(jp_file, 'r', encoding='utf-8') as f:
            jp_data = json.load(f)

        # 查找对应的中文 lng
        if script_name not in steam_lng:
            print(f"  {script_name}: 未找到对应的 Steam 中文 lng，跳过")
            continue

        total_scripts += 1

        # 合并
        merged = merge_script_translations(jp_data['texts'], steam_lng[script_name])

        matched_count = sum(1 for m in merged if m['matched'])
        total_matched += matched_count
        total_entries += len(merged)

        # 保存
        output_path = output_dir / f"{script_name}.json"
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump({
                "script": script_name,
                "total": len(merged),
                "matched": matched_count,
                "entries": merged
            }, f, ensure_ascii=False, indent=2)

        print(f"  {script_name}: {len(merged)} 条, 匹配 {matched_count} ({100*matched_count/len(merged):.1f}%)")

    print(f"\n总计:")
    print(f"  脚本数: {total_scripts}")
    print(f"  文本条目: {total_entries}")
    print(f"  已匹配: {total_matched} ({100*total_matched/total_entries:.1f}%)")
    print(f"  未匹配: {total_entries - total_matched}")


if __name__ == '__main__':
    import sys

    if len(sys.argv) < 4:
        print("用法:")
        print("  python -m tool.merge_translations <日文原文目录> <Steam中文Rio.arc> <输出目录>")
        print()
        print("示例:")
        print("  python -m tool.merge_translations \\")
        print("    tmp/script_texts \\")
        print("    backup/zh-CN/Rio.arc \\")
        print("    tmp/merged_translations")
        sys.exit(1)

    japanese_dir = sys.argv[1]
    steam_cn_arc = sys.argv[2]
    output_dir = sys.argv[3]

    batch_merge(japanese_dir, steam_cn_arc, output_dir)
