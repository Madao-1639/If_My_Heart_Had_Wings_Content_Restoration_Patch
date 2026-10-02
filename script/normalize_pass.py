"""对权威对位译文执行 tool.textfix.normalize，量化机械层能修掉多少、还剩多少要语境判断。

输出：
  tmp/norm_rows.jsonl   全量 {script, kind, idx, jp, cn_raw, cn, reason}
  tmp/norm_summary.md   分类计数 + 标记保形校验 + 每类样例
  tmp/norm_review.md    需语境判断的行（穷举，供并发评审 subagent 分批）
"""
import collections
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import tool.textfix as T  # noqa: E402

ROWS = [json.loads(l) for l in (ROOT / 'tmp' / 'pairing_final.jsonl').read_text('utf-8').splitlines()]

MARK = re.compile(r'(%K|%P|\\n)')
reason_count = collections.Counter()
changed = 0
marker_break = []
out = []
for r in ROWS:
    if r['kind'] == 'ctrl':
        out.append({**r, 'cn_raw': r['cn'], 'reason': None})
        continue
    raw = r['cn'] or ''
    norm = T.normalize(raw)
    if norm != raw:
        changed += 1
    if MARK.findall(norm) != MARK.findall(raw):
        marker_break.append((r['script'], r['idx'], raw, norm))
    reason = T.needs_review(norm, r['jp']) if r['kind'] in ('dlg', 'menu', 'flag') else None
    reason_count[reason or 'ok'] += 1
    out.append({**r, 'cn_raw': raw, 'cn': norm, 'reason': reason})

with (ROOT / 'tmp' / 'norm_rows.jsonl').open('w', encoding='utf-8') as f:
    for o in out:
        f.write(json.dumps(o, ensure_ascii=False) + '\n')

need = [o for o in out if o.get('reason')]
by_script = collections.Counter(o['script'] for o in need)

L = ['# 机械规范化后的量化结果', '',
     f'- 总行数 {len(out)}，规范化改写 {changed} 行',
     f'- 标记（%K/%P/\\n）保形校验失败 {len(marker_break)} 行',
     f'- 仍需语境判断 {len(need)} 行，覆盖 {len(by_script)} 个脚本', '',
     '## reason 分布']
for k, v in reason_count.most_common():
    L.append(f'- {k}: {v}')
L.append('')
L.append('## 规范化前后对照样例（每类 6 条）')
seen = collections.Counter()
for o in out:
    if o['cn_raw'] != o.get('cn') and seen[o.get('reason') or 'content-fix'] < 6:
        seen[o.get('reason') or 'content-fix'] += 1
        L.append(f"- [{o.get('reason')}] {o['script']} idx{o['idx']}")
        L.append(f'    raw  {o["cn_raw"]}')
        L.append(f'    norm {o["cn"]}')
L.append('')
L.append('## 标记破坏行')
for s, i, raw, norm in marker_break[:20]:
    L.append(f'- {s} idx{i}\n    raw {raw}\n    norm {norm}')
Path(ROOT / 'tmp' / 'norm_summary.md').write_text('\n'.join(L) + '\n', 'utf-8')

# 待评审清单（按脚本分组，穷举）
L = ['# 需语境判断的行（穷举）', '']
cur = None
for o in need:
    if o['script'] != cur:
        cur = o['script']
        L.append(f'\n## {cur}')
    L.append(f"- idx{o['idx']} [{o['reason']}]")
    L.append(f'    JP {o["jp"]}')
    L.append(f'    CN {o["cn"]}')
Path(ROOT / 'tmp' / 'norm_review.md').write_text('\n'.join(L) + '\n', 'utf-8')

print('rows', len(out), 'changed', changed, 'marker_break', len(marker_break))
print('reasons', dict(reason_count))
print('need review', len(need), 'scripts', len(by_script))
