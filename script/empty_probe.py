"""核对两件事：18 个空槽在日文侧到底是什么行；以及「小小鸟」两处的原文。结果写 tmp/empty_probe.md"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from tool import fancn  # noqa: E402

WANT_EMPTY = [('ASA_001', 0), ('CO1_013_A', 0), ('CO1_020', 121), ('CO1_020', 125),
              ('CO1_020', 129), ('CO1_020', 133), ('CO2_005_A', 0), ('YOR_001', 0),
              ('CO1_018_A', 0)]
WANT_TEXT = [('CO1_008', 174), ('CO1_016', 40), ('KOT_003', 1760)]

pair = {}
for line in (ROOT / 'resource' / 'corpus' / 'pairing.jsonl').read_text('utf-8').splitlines():
    r = json.loads(line)
    pair.setdefault((r['script'], r['idx']), []).append(r)

fixes = {}
for line in (ROOT / 'resource' / 'corpus' / 'review_fixes.jsonl').read_text('utf-8').splitlines():
    e = json.loads(line)
    fixes[(e['script'], e['idx'])] = e['cn']

L = ['# 空槽与小小鸟核对', '', '## 空槽']
for key in WANT_EMPTY:
    texts = fancn.load_texts(key[0])
    got = texts[key[1]] if key[1] < len(texts) else '<越界>'
    prs = pair.get(key, [])
    L.append(f'- {key[0]} idx{key[1]} 产物={got!r} 配对行={len(prs)}')
    for p in prs:
        L.append(f'    kind={p["kind"]} jp={p["jp"]!r} raw_cn={p["cn"]!r}')
L.append('')
L.append('## 「小小鸟」')
for key in WANT_TEXT:
    texts = fancn.load_texts(key[0])
    L.append(f'- {key[0]} idx{key[1]}')
    for p in pair.get(key, []):
        L.append(f'    JP {p["jp"]}')
        L.append(f'    RAW {p["cn"]}')
        L.append(f'    FIX {fixes.get(key, "—")}')
    L.append(f'    产物 {texts[key[1]] if key[1] < len(texts) else "<越界>"}')
(ROOT / 'tmp' / 'empty_probe.md').write_text('\n'.join(L) + '\n', 'utf-8')
print('probed', len(WANT_EMPTY), len(WANT_TEXT))
