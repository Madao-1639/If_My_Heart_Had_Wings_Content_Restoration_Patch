"""人名/昵称一致性抽查：对若干日文昵称词，统计其中文译法分布，找出少数派写法。

判据：某行日文含目标词，取该行中文里目标位置附近的写法归类（用关键词匹配）。
结果写 tmp/nickname_scan.md
"""
import collections
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from tool import textfix  # noqa: E402

# 目标：日文昵称 -> 中文可能写法集合
TARGETS = {
    'ことりん': ['小小鸟', '小鸟', '小鸠', '科托琳'],
    '小鳥ちゃん': ['小鸟酱', '小鸟-chan', '小鸟'],
    'あげは': ['扬羽', '蝶羽', '阿几何', 'あげは'],
    'あーちゃん': ['扬姐姐', '扬姐', '扬羽姐'],
    '天音先輩': ['天音学姐', '天音前辈', '天音先輩'],
    '小鳥先輩': ['小鸟学姐', '小鸟前辈'],
    '碧先輩': ['碧学长', '碧前辈'],
    'イスカ': ['易鸟', '斯卡', '伊斯卡'],
    'ひばり': ['扬羽', '云雀', 'ひばり'],
}

fixes = {}
for line in (ROOT / 'resource' / 'corpus' / 'review_fixes.jsonl').read_text('utf-8').splitlines():
    e = json.loads(line)
    fixes[(e['script'], e['idx'])] = e['cn']

stat = {k: collections.Counter() for k in TARGETS}
minor = collections.defaultdict(list)
for line in (ROOT / 'resource' / 'corpus' / 'pairing.jsonl').read_text('utf-8').splitlines():
    r = json.loads(line)
    if r['kind'] not in ('dlg', 'menu', 'flag'):
        continue
    jp = r['jp'] or ''
    cn = textfix.emit(jp, r['cn'] or '', fixes.get((r['script'], r['idx'])))
    for tgt, forms in TARGETS.items():
        if tgt not in jp:
            continue
        hit = [f for f in forms if f in cn]
        # 按"最长匹配优先"认定实际写法，避免"小鸟"吞掉"小小鸟"
        if len(hit) > 1:
            hit = [max(hit, key=len)]
        key = hit[0] if hit else '（未命中）'
        stat[tgt][key] += 1
        if hit and len(hit[0]) < max(len(x) for x in forms if x in stat[tgt]):
            pass
        minor[(tgt, key)].append((r['script'], r['idx'], jp[:60], cn[:70]))

L = ['# 昵称与称谓译法分布', '']
for tgt, forms in TARGETS.items():
    total = sum(stat[tgt].values())
    L.append(f'## {tgt}（{total} 行）')
    for k, v in stat[tgt].most_common():
        L.append(f'- {k}: {v}')
        if v <= max(2, total * 0.05) and k != '（未命中）':
            for s, i, jp, cn in minor[(tgt, k)][:4]:
                L.append(f'    {s} idx{i} JP {jp}')
                L.append(f'        CN {cn}')
    L.append('')
(ROOT / 'tmp' / 'nickname_scan.md').write_text('\n'.join(L) + '\n', 'utf-8')
print(ascii({k: dict(v) for k, v in stat.items()}))
