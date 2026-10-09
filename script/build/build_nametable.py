"""NameTable 构建器 —— 官方译名表 + 补充条目 → 合并后的 NameTable.txt 字节。

机制
----
`zh-CN/Rio.arc` 的 `NameTable.txt` 成员是 UTF-16LE 文本（无 BOM，`\\r\\n` 行尾），
每行 `名字串\\t中文译名`。引擎显示说话人名牌（WS2 `0x15` 指令的操作数字符串，
形如 `%LCKotori`）时，用**整串精确匹配**查表；查不到则原样显示。

官方 Steam 底本是英文（名字串为英文），官方表只覆盖英文键；还原脚本
（L4 后日谈 `SL_*`、L1–L3 插回的原版脚本段落）使用日文底本，名字串为
`%LC小鳥` 这类日文键，官方表查不到 ⇒ 名牌显示日文。

本构建器把补充条目合并进官方表：`resource/fan_cn/NameTable.json`（L2 的
译文构建产物，日文说话名 → 中文译名，读取时把组合名分隔符 `·`(U+00B7) 归一为
官方值域使用的 `・`(U+30FB)）。这张 JSON 是补充条目的唯一来源；要改某个显示名，
入口是机械层的 `tool/textfix.py` `NAME_FIX` 显式条目（重建后落进 JSON）。
合并规则：同键覆盖（可修正官方译名）、新键追加在表尾。
产出供 `script/build/build_l4.py`（G10）与本体线的 zh-CN 构建共同消费。

幂等：官方表读取自只读 `backup/`，合并为纯函数，重复运行结果逐字节一致。
"""
import argparse
import json
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BASE))

from tool import arcbuild  # noqa: E402

OFFICIAL_ARC = BASE / 'backup' / 'zh-CN' / 'Rio.arc'
OFFICIAL_MEMBER = 'NameTable.txt'
FAN_TABLE = BASE / 'resource' / 'fan_cn' / 'NameTable.json'
DOT_FAN = '\u00b7'       # ·  L2 表组合名用的中点
DOT_OFFICIAL = '\u30fb'  # ・ 官方值域唯一使用的中点


def parse_nametable(data):
    """官方 NameTable.txt 字节 → [(key, value)]（保序）。"""
    text = data.decode('utf-16-le')
    out = []
    for line in text.split('\r\n'):
        if not line:
            continue
        key, sep, val = line.partition('\t')
        assert sep, 'malformed NameTable line: %r' % line
        out.append((key, val))
    return out


def parse_fan_table(path):
    """L2 的 NameTable.json（键 → 中文译名）→ [(key, value)]（保序）。

    值的组合名中点 `·` 归一为官方值域的 `・`；键不动（脚本侧名字串用的就是 `・`）。
    """
    rows = json.loads(Path(path).read_text(encoding='utf-8'))
    return [(k, v.replace(DOT_FAN, DOT_OFFICIAL)) for k, v in rows.items()]


def merge(official, overrides):
    """官方条目保序在前（同键被覆盖），新键按补充条目顺序追加在后。"""
    ov = dict(overrides)
    merged = []
    seen = set()
    for k, v in official:
        merged.append((k, ov.get(k, v)))
        seen.add(k)
    for k, v in overrides:
        if k not in seen:
            merged.append((k, v))
            seen.add(k)
    return merged


def serialize(entries):
    """[(key, value)] → NameTable.txt 字节（UTF-16LE 无 BOM，\\r\\n 行尾）。"""
    text = '\r\n'.join('%s\t%s' % (k, v) for k, v in entries) + '\r\n'
    return text.encode('utf-16-le')


def build(official_arc=OFFICIAL_ARC, fan_table=FAN_TABLE):
    member = [(n, d) for n, d in arcbuild.read_raw(official_arc)
              if n.decode('utf-16-le') == OFFICIAL_MEMBER]
    assert len(member) == 1, 'NameTable.txt not found in %s' % official_arc
    official = parse_nametable(member[0][1])
    overrides = parse_fan_table(fan_table)
    merged = merge(official, overrides)
    return serialize(merged), official, overrides


def main():
    ap = argparse.ArgumentParser(description='构建合并后的 NameTable.txt')
    ap.add_argument('--official', default=str(OFFICIAL_ARC))
    ap.add_argument('--fan-table', default=str(FAN_TABLE))
    ap.add_argument('--out', required=True, help='输出文件路径')
    args = ap.parse_args()
    data, official, overrides = build(args.official, args.fan_table)
    Path(args.out).write_bytes(data)
    print('official %d entries + supplement %d entries -> %s (%d B)'
          % (len(official), len(overrides), args.out, len(data)))


if __name__ == '__main__':
    main()
