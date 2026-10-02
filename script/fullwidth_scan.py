"""统计规范化后中文里残留的全角数字/全角拉丁字母（日文排版习惯残留），评估是否值得统一为半角。

结果写 tmp/fullwidth_scan.md：命中行数、按字符分布、样例。
"""
import collections
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from tool import textfix  # noqa: E402

FW = re.compile(r'[０-９Ａ-Ｚａ-ｚ]')

fixes = {}
for line in (ROOT / 'resource' / 'corpus' / 'review_fixes.jsonl').read_text('utf-8').splitlines():
    e = json.loads(line)
    fixes[(e['script'], e['idx'])] = e['cn']

rows_hit = 0
chars = collections.Counter()
samples = []
for line in (ROOT / 'resource' / 'corpus' / 'pairing.jsonl').read_text('utf-8').splitlines():
    r = json.loads(line)
    if r['kind'] not in ('dlg', 'menu', 'flag'):
        continue
    cn = textfix.emit(r['jp'] or '', r['cn'] or '', fixes.get((r['script'], r['idx'])))
    m = FW.findall(cn)
    if not m:
        continue
    rows_hit += 1
    chars.update(m)
    if len(samples) < 40:
        samples.append((r['script'], r['idx'], cn))

L = ['# 全角数字/拉丁残留', '', f'- 命中 {rows_hit} 行', '', '## 字符分布']
L += [f'- {c}: {n}' for c, n in sorted(chars.items(), key=lambda x: -x[1])]
L += ['', '## 样例']
for script, idx, cn in samples:
    L.append(f'- {script} idx{idx}')
    L.append(f'    {cn}')
(ROOT / 'tmp' / 'fullwidth_scan.md').write_text('\n'.join(L) + '\n', 'utf-8')
print('rows_hit', rows_hit, 'distinct_chars', len(chars))
