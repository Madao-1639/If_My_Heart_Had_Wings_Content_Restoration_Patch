"""找"译校批注混进正文"的行：中文有括注、日文却没有对应括注（或中文出现 ＊/※/* 式旁注）。

民汉表里混着译校者给读者/给润色的说明，这些内容在游戏里会直接上屏，必须剥掉。
判据用日文对照，避免误删日文本身就有的内心独白括注（如「（…）」）。结果写 tmp/paren_notes.md。
"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from tool import textfix  # noqa: E402

CN_PAREN = re.compile(r'[（(]([^（()）]{4,})[）)]')
STRAY = re.compile(r'[＊*※]\s*[^%]{0,3}?(?:注|译注|译者注|按)[：:]|^\s*(?:译注|注)[：:]')

fixes = {}
for line in (ROOT / 'resource' / 'corpus' / 'review_fixes.jsonl').read_text('utf-8').splitlines():
    e = json.loads(line)
    fixes[(e['script'], e['idx'])] = e['cn']

L = ['# 疑似混入正文的译校批注', '', '## 中文有括注、日文没有', '']
n_paren = n_stray = 0
for line in (ROOT / 'resource' / 'corpus' / 'pairing.jsonl').read_text('utf-8').splitlines():
    r = json.loads(line)
    if r['kind'] != 'dlg':
        continue
    jp = r['jp'] or ''
    cn = textfix.emit(jp, r['cn'] or '', fixes.get((r['script'], r['idx'])))
    jp_has_paren = bool(re.search(r'[（(「『【]', jp))
    for inner in CN_PAREN.findall(cn):
        if not jp_has_paren:
            n_paren += 1
            L.append(f'- {r["script"]} idx{r["idx"]}')
            L.append(f'    JP {jp}')
            L.append(f'    CN {cn}')
            break
    if STRAY.search(cn):
        n_stray += 1
        L.append(f'- [旁注符号] {r["script"]} idx{r["idx"]}')
        L.append(f'    JP {jp}')
        L.append(f'    CN {cn}')
L.insert(3, f'- 无日文对应的中文括注 {n_paren} 行；带 ＊/※/注： 旁注符号 {n_stray} 行')
(ROOT / 'tmp' / 'paren_notes.md').write_text('\n'.join(L) + '\n', 'utf-8')
print('cn_paren_only', n_paren, 'stray_marker', n_stray)
