"""同一槽位的三方对照：日文原句 / 官方 zh-CN / 民间 zh-CN。

用于裁决"民间与官方术语分歧"到底哪边偏离原文（会长vs社长、部员vs社员、滑翔部vs滑翔机社）。
结果写 tmp/three_way.md
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from tool import arcbuild, fancn, lng as lng_codec  # noqa: E402

SLOTS = [('AGE_001', 17), ('AGE_001', 18), ('AGE_001', 87), ('AGE_001', 114),
         ('AGE_001', 607), ('AGE_001', 526), ('AGE_001', 156), ('AGE_002', 413),
         ('AGE_002', 440), ('AGE_003', 5), ('KOT_007', 695), ('AMA_003', 469),
         ('AGE_008', 224), ('AGE_008', 226), ('CO1_014', 182)]
want = {k: i for i, k in enumerate(SLOTS)}

jp = {}
for line in (ROOT / 'resource' / 'corpus' / 'pairing.jsonl').read_text('utf-8').splitlines():
    r = json.loads(line)
    key = (r['script'], r['idx'])
    if key in want:
        jp[key] = (r.get('jp', ''), r.get('cn', ''), r['kind'])

import pathlib  # noqa: E402
fan = {}
for s, i in SLOTS:
    fan[(s, i)] = fancn.load_map(s).get(i, '')

off = {}
for name_bytes, data in arcbuild.read_raw(ROOT / 'backup' / 'zh-CN' / 'Rio.arc'):
    name = name_bytes.decode('utf-16le')
    if not name.lower().endswith('.lng'):
        continue
    try:
        texts = lng_codec.parse_lng(data, key=lng_codec.KEY_STEAM_ZHCN)
    except ValueError:
        continue
    stem = name.rsplit('.', 1)[0]
    for s, i in SLOTS:
        if s == stem and i < len(texts):
            off[(s, i)] = texts[i]

L = ['# 三方对照（日文 / 官方中文 / 民间中文）', '']
for s, i in SLOTS:
    j, _, kind = jp.get((s, i), ('', '', '?'))
    L += [f'## {s} idx{i}（{kind}）', f'- JP  {j}', f'- OFF {off.get((s, i), "—")}',
          f'- FAN {fan.get((s, i), "—")}', '']
(ROOT / 'tmp' / 'three_way.md').write_text('\n'.join(L) + '\n', 'utf-8')
print('slots', len(SLOTS), 'jp', len(jp), 'off', len(off), 'fan', len(fan))
