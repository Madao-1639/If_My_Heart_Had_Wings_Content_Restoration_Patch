"""从 WS2 脚本中提取日文原文，生成每个脚本的文本列表。

由于 oozora_CHSpatch 的翻译表中只存储了 {CRC32: 中文译文}，没有日文原文，
无法直接建立映射。本工具提取日文原文供后续处理：
1. 手动校对
2. 机翻辅助
3. 作为内容恢复补丁的开发参考
"""
import re
import json
import struct
from pathlib import Path
import sys
sys.path.append('..')
from tool import ws2, arcbuild


# 角色名标记：\x15 %LC <Shift-JIS角色名> \x00
CHAR_NAME_PATTERN = re.compile(rb'\x15(%LC[\x80-\xff\x20-\x7f]+?)\x00', re.DOTALL)

# 对话行：\x14 <idx:u16> <flag:u16> char\x00 <Shift-JIS对白> %K%P 或 %P 或 %K
#
# 匹配规则：
# 1. 一个文本框内可以包含多个由 %K 分隔的段落，引擎把整段文本（含内嵌 %K）
#    一次性传给 MultiByteToWideChar 计算 CRC32
# 2. 结束模式：
#    - %K%P（最常见，50,984条）
#    - 单独 %P（无 %K）
#    - 单独 %K（少数情况，后面不是 %P 则停止）
# 3. 关键点：匹配 [^%]* 确保不会跨越下一个 % 标记，避免误匹配到 FLAG_CHECK
#
# 详见 ../oozora_CHSpatch/fanchn-crc32-matching-issue.md §3.7
DIALOGUE_PATTERN = re.compile(
    rb'\x14(.{2})(.{2})char\x00((?:[\x80-\xff\x00-\x7f])*?(?:%K%P|%K(?!%P)|(?<!%K)%P))',
    re.DOTALL
)


def extract_script_text(ws2_data):
    """从 WS2 脚本中提取所有对白文本。

    返回:
        list of dict: [{"lng_idx": int, "text": str, "text_with_name": str or None, "char_name": str or None}, ...]

    说明:
        - text: 纯对话文本（不含 %LC 角色名前缀）
        - text_with_name: 带角色名前缀的完整文本（如果有角色名）
        - char_name: 角色名（不含 %LC 前缀）
    """
    decoded = ws2.decode(ws2_data)
    results = []

    # 提取所有角色名标记
    char_names = {}
    for match in CHAR_NAME_PATTERN.finditer(decoded):
        char_names[match.end()] = match.group(1)

    # 提取所有对话行
    for match in DIALOGUE_PATTERN.finditer(decoded):
        idx_bytes = match.group(1)
        dialogue_text = match.group(3)

        lng_idx = struct.unpack('<H', idx_bytes)[0]

        # 验证对话文本是否可以完整解码（排除误匹配到二进制数据的情况）
        try:
            dialogue_text.decode('cp932')
        except UnicodeDecodeError:
            # 解码失败，说明匹配跨越了 FLAG_CHECK 等二进制边界，跳过
            continue

        # 查找最近的角色名标记
        char_name_prefix = b''
        char_name_only = None
        for name_end_pos in sorted(char_names.keys(), reverse=True):
            if name_end_pos < match.start() and match.start() - name_end_pos < 100:
                char_name_prefix = char_names[name_end_pos]
                # 提取 %LC 后面的角色名部分
                try:
                    char_name_only = char_name_prefix[3:].decode('cp932')  # 跳过 %LC
                except Exception:
                    char_name_only = None
                break

        # 纯对话文本（不含角色名）
        try:
            text_str = dialogue_text.decode('cp932')
        except Exception:
            text_str = f"[解码失败: {dialogue_text.hex()[:60]}...]"

        # 带角色名的完整文本
        text_with_name = None
        if char_name_prefix:
            try:
                text_with_name = (char_name_prefix + dialogue_text).decode('cp932')
            except Exception:
                pass

        results.append({
            "lng_idx": lng_idx,
            "text": text_str,
            "text_with_name": text_with_name,
            "char_name": char_name_only
        })

    return results


def batch_extract(arc_path, output_dir):
    """批量提取归档中所有脚本的文本。

    参数:
        arc_path: Rio.arc 归档路径
        output_dir: 输出目录
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    print(f"读取归档: {arc_path}")
    members = arcbuild.read_raw(arc_path)

    total_scripts = 0
    total_texts = 0

    for name_bytes, data in members:
        try:
            name = name_bytes.decode('utf-16le')
        except Exception:
            continue

        if not name.lower().endswith('.ws2'):
            continue

        total_scripts += 1
        script_name = Path(name).stem

        # 提取文本
        texts = extract_script_text(data)
        if not texts:
            continue

        total_texts += len(texts)

        # 保存为 JSON
        output_path = output_dir / f"{script_name}.json"
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump({
                "script": script_name,
                "total": len(texts),
                "texts": texts
            }, f, ensure_ascii=False, indent=2)

        print(f"  {script_name}: {len(texts)} 条文本")

    print(f"\n总计:")
    print(f"  脚本数: {total_scripts}")
    print(f"  文本数: {total_texts}")


def batch_extract_loose_rio(rio_dir, output_dir):
    """批量提取 RIO/ 目录中的裸脚本文本。

    参数:
        rio_dir: RIO/ 目录路径
        output_dir: 输出目录
    """
    rio_path = Path(rio_dir)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    print(f"读取 RIO/ 目录: {rio_path}")
    if not rio_path.exists():
        print(f"  目录不存在")
        return

    total_scripts = 0
    total_texts = 0

    for ws2_file in sorted(rio_path.glob('*.ws2')):
        with open(ws2_file, 'rb') as f:
            data = f.read()

        total_scripts += 1
        script_name = ws2_file.stem

        # 提取文本
        texts = extract_script_text(data)
        if not texts:
            continue

        total_texts += len(texts)

        # 保存为 JSON
        output_path = output_dir / f"{script_name}_rio.json"
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump({
                "script": script_name,
                "source": "RIO",
                "total": len(texts),
                "texts": texts
            }, f, ensure_ascii=False, indent=2)

        print(f"  {script_name}: {len(texts)} 条文本")

    print(f"\n总计:")
    print(f"  脚本数: {total_scripts}")
    print(f"  文本数: {total_texts}")


if __name__ == '__main__':
    import sys

    if len(sys.argv) < 3:
        print("用法:")
        print("  python -m tool.extract_script_text <Rio.arc> <输出目录>")
        print()
        print("示例:")
        print("  python -m tool.extract_script_text \\")
        print("    ../在这片天空下展开一双翅膀(羽翼汉化版V1.0beta2)/Rio.arc \\")
        print("    tmp/script_texts")
        sys.exit(1)

    arc_path = sys.argv[1]
    output_dir = sys.argv[2]

    batch_extract(arc_path, output_dir)
