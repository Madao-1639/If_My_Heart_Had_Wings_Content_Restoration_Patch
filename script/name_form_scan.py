"""扫描产物 JSON 里的日式新字体残留与人名异形（译名不统一类缺陷）。

A. 日式新字体：LCMapStringW(2052) 不覆盖的日文字形（瀬/亜/覚/図…），逐条点名；
B. 主要人名的中文写法分布，用来判断是否存在跨脚本异形。
结果写 tmp/name_form_scan.md
"""
import collections
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from tool import fancn  # noqa: E402

JP_FORM = {
    '亜': '亚', '悪': '恶', '隠': '隐', '栄': '荣', '絵': '绘', '覚': '觉',
    '図': '图', '対': '对', '単': '单', '桜': '樱', '応': '应', '囲': '围',
    '曽': '曾', '滝': '泷', '瀬': '濑', '穏': '稳', '関': '关', '仏': '佛',
    '畳': '叠', '駅': '站', '俵': '表', '渕': '渊', '槙': '槌', '戸': '户',
    '弁': '辨',
}
NAMES = ['依瑠', '依留', '亜纱', '亚纱', '亜紗', '亚紗', '水瀬', '水濑', '小鳥',
         '小鸟', '揚羽', '扬羽', '天音', '佳奈子', '加奈子', '朱莉', '易鸟',
         '哈特', '蛍', '萤', '莹', '碧', '小鳥ちゃん']

rows = collections.Counter()
detail = collections.defaultdict(list)
per_script = collections.defaultdict(collections.Counter)
for name in fancn.script_names():
    for i, t in enumerate(fancn.load_texts(name)):
        if not t:
            continue
        for ch in set(t) & set(JP_FORM):
            rows[ch] += 1
            if len(detail[ch]) < 8:
                detail[ch].append((name, i, t))
            per_script[name][ch] += 1
        for n in NAMES:
            if n in t:
                per_script[name][n] += t.count(n)

L = ['# 日式字形与人名异形扫描（产物口径）', '', '## A. 日式新字体残留']
for ch, n in rows.most_common():
    L.append(f'- {ch}（对应简中 {JP_FORM[ch] or "—"}）: {n} 行')
    for s, i, t in detail[ch]:
        L.append(f'    {s} idx{i} {t}')
L += ['', '## B. 人名写法 × 脚本']
for s in sorted(per_script):
    hits = {k: v for k, v in per_script[s].items() if k in NAMES}
    if hits:
        L.append(f'- {s}: ' + ' '.join(f'{k}×{v}' for k, v in sorted(hits.items())))
(ROOT / 'tmp' / 'name_form_scan.md').write_text('\n'.join(L) + '\n', 'utf-8')
print('jp_form', ascii(dict(rows)))
tot = collections.Counter()
for s in per_script.values():
    for k, v in s.items():
        if k in NAMES:
            tot[k] += v
print('names', ascii(dict(tot)))
