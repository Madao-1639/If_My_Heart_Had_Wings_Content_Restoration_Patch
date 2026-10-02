"""取指定脚本 idx 窗口内的 JP/CN 对照，用于人工复核批注删除后是否留下突兀行。

只读；结果写 tmp/lowconf_ctx.md。
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

WANT = [('CO1_011', 296, 305), ('CO1_016', 498, 508), ('CO2_003', 413, 426),
        ('CO2_004', 88, 96), ('HUT_005', 216, 226), ('CO1_009', 660, 668),
        ('CO1_018_E', 180, 188)]
ranges = {s: (a, b) for s, a, b in WANT}

L = ['# 低把握槽位上下文', '']
for line in (ROOT / 'resource' / 'corpus' / 'pairing.jsonl').read_text('utf-8').splitlines():
    r = json.loads(line)
    s = r['script']
    if s in ranges and r['idx'] is not None and ranges[s][0] <= r['idx'] <= ranges[s][1]:
        mark = '  <<<' if r.get('cn') and ('（' in r['cn'] or '(' in r['cn']) else ''
        L.append(f'- {s} idx{r["idx"]} [{r["kind"]}]{mark}')
        L.append(f'    JP {r.get("jp", "")}')
        L.append(f'    CN {r.get("cn", "")}')
(ROOT / 'tmp' / 'lowconf_ctx.md').write_text('\n'.join(L) + '\n', 'utf-8')
print('lines', len(L))
