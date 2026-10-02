"""生成拟声词括号注释的改写批次键表：tmp/glossp_batch_NN.keys.json

判据直接复用 script/gloss_paren.py 的 collect()，只取 A（括注即整行）与 B（正文夹注）两档；
C 档（日文用破折号做同位语）不动。每行带 ±3 行的日文/中文上下文，供评审 subagent 选词。
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'script'))
from gloss_paren import collect  # noqa: E402

N_BATCH = 4
WINDOW = 3

rows = [json.loads(l) for l in (ROOT / 'resource' / 'corpus' / 'pairing.jsonl').read_text('utf-8').splitlines()]
by_script = {}
for r in rows:
    if r['idx'] is not None:
        by_script.setdefault(r['script'], {})[r['idx']] = r

fixes = {}
for l in (ROOT / 'resource' / 'corpus' / 'review_fixes.jsonl').read_text('utf-8').splitlines():
    d = json.loads(l)
    fixes[(d['script'], d['idx'])] = d['cn']

a, b, _c = collect()
targets = a + b
targets.sort(key=lambda r: (r['script'], r['idx']))

for n in range(N_BATCH):
    part = targets[n::N_BATCH]
    keys = []
    for r in part:
        idxs = by_script[r['script']]
        ctx = []
        for i in range(r['idx'] - WINDOW, r['idx'] + WINDOW + 1):
            if i == r['idx'] or i not in idxs:
                continue
            ctx.append({'idx': i, 'jp': idxs[i]['jp'],
                        'cn': fixes.get((r['script'], i)) or idxs[i]['cn'] or ''})
        keys.append({'script': r['script'], 'idx': r['idx'], 'tier': 'A' if r['bare'] else 'B',
                     'jp': r['jp'], 'cn': r['cn'], 'ctx': ctx})
    out = ROOT / 'tmp' / f'glossp_batch_{n:02d}.keys.json'
    out.write_text(json.dumps({'count': len(keys), 'rows': keys}, ensure_ascii=False, indent=1),
                   'utf-8')
    print(out.name, len(keys))

print('targets', len(targets), 'A', len(a), 'B', len(b))
