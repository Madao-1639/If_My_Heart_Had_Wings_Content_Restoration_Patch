"""核对 paren_notes 报告里的行是否进入了批注判定批次；未进入的写 tmp/note_uncovered.md。"""
import glob
import io
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from tool import textfix  # noqa: E402

PAREN = re.compile(r'[（(]([^（()）]{2,})[）)]')

inbatch = set()
for p in sorted(glob.glob(str(ROOT / 'tmp' / 'note_batch_*.keys.json'))):
    for l in Path(p).read_text('utf-8').splitlines():
        if l.strip():
            e = json.loads(l)
            inbatch.add((e['script'], e['idx']))

fixes = {}
for line in (ROOT / 'resource' / 'corpus' / 'review_fixes.jsonl').read_text('utf-8').splitlines():
    e = json.loads(line)
    fixes[(e['script'], e['idx'])] = e['cn']

out = io.StringIO()
out.write('# 未进批次的中文括注行\n\n')
n = miss = 0
for line in (ROOT / 'resource' / 'corpus' / 'pairing.jsonl').read_text('utf-8').splitlines():
    r = json.loads(line)
    if r['kind'] not in ('dlg', 'menu', 'flag'):
        continue
    jp = r['jp'] or ''
    cn = textfix.emit(jp, r['cn'] or '', fixes.get((r['script'], r['idx'])))
    if len(PAREN.findall(cn)) <= len(PAREN.findall(jp)):
        continue
    n += 1
    if (r['script'], r['idx']) in inbatch:
        continue
    miss += 1
    out.write(f'- {r["script"]} idx{r["idx"]} kind={r["kind"]}\n')
    out.write(f'    JP {jp}\n')
    out.write(f'    CN {cn}\n')
out.write(f'\n- 现存括注多余行 {n}，其中未进批次 {miss}\n')
(ROOT / 'tmp' / 'note_uncovered.md').write_text(out.getvalue(), 'utf-8')
print('total', n, 'uncovered', miss)
