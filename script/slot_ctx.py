"""按槽位导出日文/民间中文及其上下文窗口：python script/slot_ctx.py HUT_005:222 ASA_001:832

只读 resource/corpus/pairing.jsonl，明细写 tmp/slot_ctx.md（UTF-8），控制台只输出 ASCII 计数。
"""
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
W = int(os.environ.get('SLOT_CTX_W', '5'))

by_script = {}
order = {}
for l in (ROOT / 'resource' / 'corpus' / 'pairing.jsonl').read_text('utf-8').splitlines():
    r = json.loads(l)
    if r['idx'] is None:
        continue
    by_script.setdefault(r['script'], {})[r['idx']] = (r['jp'] or '', r['cn'] or '')
    order.setdefault(r['script'], []).append(r['idx'])

L = ['# 槽位上下文']
for arg in sys.argv[1:]:
    script, idx = arg.split(':')
    idx = int(idx)
    L.append(f'\n## {script} idx{idx}')
    for i in sorted([i for i in order.get(script, []) if abs(i - idx) <= W]):
        jp, cn = by_script[script][i]
        L.append(f'{"->" if i == idx else "  "} idx{i} | JP {jp}')
        L.append(f'      | CN {cn}')
out = ROOT / 'tmp' / 'slot_ctx.md'
out.write_text('\n'.join(L) + '\n', 'utf-8')
print(f'slots={len(sys.argv) - 1} report={out.name}')
