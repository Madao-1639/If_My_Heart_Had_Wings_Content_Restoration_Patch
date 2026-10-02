"""点名列出所有含"待机械改写"字符/词的产物行，供改写前逐条确认。

目标集合 = 日式新字体（18 字）+ 未译日文词（寮母 / 单独的寮 / 部室）+ 半角钩括 ｢｣。
特别要确认：寮 出现在非"寮母"语境时的具体含义。
结果写 tmp/glyph_targets.md
"""
import collections
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from tool import fancn  # noqa: E402

GLYPHS = '亜瀬戸恵蛍変効対殻姉亀妬爲臓様搾晩徳畳'
groups = collections.defaultdict(list)
for name in fancn.script_names():
    for i, t in enumerate(fancn.load_texts(name)):
        if not t:
            continue
        for ch in set(t) & set(GLYPHS):
            groups[f'glyph-{ch}'].append((name, i, t))
        if re.search(r'寮(?!母)', t):
            groups['word-寮(非寮母)'].append((name, i, t))
        if '寮母' in t:
            groups['word-寮母'].append((name, i, t))
        if '部室' in t:
            groups['word-部室'].append((name, i, t))
        if '｢' in t or '｣' in t:
            groups['sym-半角钩括'].append((name, i, t))

L = ['# 待机械改写点名的行', '']
for k in sorted(groups, key=lambda x: (-len(groups[x]), x)):
    L.append(f'## {k} ×{len(groups[k])}')
    for s, i, t in groups[k][:12]:
        L.append(f'- {s} idx{i} {t}')
    L.append('')
(ROOT / 'tmp' / 'glyph_targets.md').write_text('\n'.join(L) + '\n', 'utf-8')
print(ascii({k: len(v) for k, v in groups.items()}))
