"""扫描菜单项 / FLAG 标签行里的漏删批注（批注判定批次只覆盖 dlg 行）。

判据同 tmp/note_batches.py：规范化后中文圆括注组数 > 日文圆括注组数。
另附「中文有括注而日文整行无括号」的强嫌疑子集。结果写 tmp/menu_notes.md。
"""
import collections
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from tool import textfix  # noqa: E402

PAREN = re.compile(r'[（(]([^（()）]{2,})[）)]')

fixes = {}
for line in (ROOT / 'resource' / 'corpus' / 'review_fixes.jsonl').read_text('utf-8').splitlines():
    e = json.loads(line)
    fixes[(e['script'], e['idx'])] = e['cn']

hits = []
for line in (ROOT / 'resource' / 'corpus' / 'pairing.jsonl').read_text('utf-8').splitlines():
    r = json.loads(line)
    if r['kind'] not in ('menu', 'flag'):
        continue
    jp = r['jp'] or ''
    cn = textfix.emit(jp, r['cn'] or '', fixes.get((r['script'], r['idx'])))
    a, b = PAREN.findall(cn), PAREN.findall(jp)
    if len(a) <= len(b):
        continue
    hits.append({'script': r['script'], 'idx': r['idx'], 'kind': r['kind'],
                 'jp': jp, 'cn': cn, 'extra': [x for x in a if x not in b]})

L = ['# 菜单/标签行的漏删批注', '', f'- 命中 {len(hits)} 行', '']
for h in hits:
    L.append(f"- {h['script']} idx{h['idx']} kind={h['kind']} extra={h['extra']}")
    L.append(f"    JP {h['jp']}")
    L.append(f"    CN {h['cn']}")
(ROOT / 'tmp' / 'menu_notes.md').write_text('\n'.join(L) + '\n', 'utf-8')
print(collections.Counter(h['kind'] for h in hits), 'hits', len(hits))
