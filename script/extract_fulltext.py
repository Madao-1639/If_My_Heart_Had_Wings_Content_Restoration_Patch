"""完整提取所有脚本的中文译文。

从 Steam 中文版 lng 文件中提取所有译文，以 JSON 格式保存，
每个脚本一个文件，方便后续编辑和管理。

输出格式：
{
  "script": "ASA_001",
  "source": "Steam zh-CN",
  "entries": [
    {"index": 0, "text": "系统"},
    {"index": 1, "text": "………。"},
    ...
  ]
}
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


def parse_lng_no_xor(raw):
    """解析 lng 文件（无 XOR 加密，适用于本游戏）。"""
    import struct
    count = struct.unpack_from('<I', raw, 0)[0]
    lens = struct.unpack_from('<%dH' % count, raw, 4)
    off = 4 + 2 * count
    out = []
    for length in lens:
        chunk = raw[off:off + length]
        off += length
        try:
            text = chunk.decode('utf-16le').rstrip('\x00')
            out.append(text)
        except Exception:
            out.append(None)  # 解码失败返回 None
    return out


def extract_lng_to_json(lng_data, script_name):
    """将 lng 文件解析为 JSON 格式。

    参数:
        lng_data: lng 文件的二进制数据
        script_name: 脚本名称

    返回:
        dict: {"script": str, "source": str, "entries": [...]}
    """
    texts = parse_lng_no_xor(lng_data)

    entries = []
    for i, text in enumerate(texts):
        if text is None:
            text = ""
        entries.append({
            "index": i,
            "text": text
        })

    return {
        "script": script_name,
        "source": "Steam zh-CN",
        "total": len(entries),
        "entries": entries
    }


def batch_extract_lng_to_fulltext(steam_arc, output_dir):
    """批量提取所有 lng 文件为 JSON 格式。

    参数:
        steam_arc: Steam 中文版 Rio.arc 路径
        output_dir: 输出目录（fulltext/zh/）
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    print(f"从 Steam 中文版提取译文: {steam_arc}")
    print(f"输出目录: {output_dir}")
    print()

    members = arcbuild.read_raw(steam_arc)

    extracted_count = 0
    total_entries = 0

    for name_bytes, data in members:
        try:
            name = name_bytes.decode('utf-16le')
        except Exception:
            continue

        if not name.lower().endswith('.lng'):
            continue

        script_name = Path(name).stem

        # 解析 lng 文件
        try:
            result = extract_lng_to_json(data, script_name)
        except Exception as e:
            print(f"  [FAIL] {name}: {e}")
            continue

        # 保存为 JSON
        output_path = output_dir / f"{script_name}.json"
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(result, f, ensure_ascii=False, indent=2)

        extracted_count += 1
        total_entries += result['total']
        print(f"  [OK] {script_name}.json: {result['total']} entries")

    print()
    print("=" * 60)
    print(f"总计: {extracted_count} 个脚本, {total_entries} 条译文")
    print(f"输出目录: {output_dir}")


if __name__ == '__main__':
    import sys

    if len(sys.argv) < 3:
        print("用法:")
        print("  python -m tool.extract_fulltext <Steam中文Rio.arc> <输出目录>")
        print()
        print("示例:")
        print("  python -m tool.extract_fulltext \\")
        print("    backup/zh-CN/Rio.arc \\")
        print("    fulltext/zh")
        sys.exit(1)

    steam_arc = sys.argv[1]
    output_dir = sys.argv[2]

    batch_extract_lng_to_fulltext(steam_arc, output_dir)
