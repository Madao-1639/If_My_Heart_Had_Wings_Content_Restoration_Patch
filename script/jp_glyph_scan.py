"""扫描中文正文里的日式专用字形与未译外来词，为批注删除后的可读性复查做准备。

两类目标：
  A. 日文汉字（简中不用）：畳 / 辺（用于"附近"义）/ 駅 / 囲 等，逐条点名；
  B. 纯拉丁缩略词（OB、NG、IC…）——若它旁边的中文括注刚被删掉，就会变成未译外来词。
结果写 tmp/jp_glyph_scan.md
"""
import collections
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from tool import textfix  # noqa: E402

JP_ONLY = ('畳辺駅囲懐沢渕槇郞凪梛柊'
           '毎髙嶋邉繋枠込廻辻桧栞鉾頴凜峯'
           '鴎瀧穂蒜苺葺峠曽'
           # 不收「崎」：实测 8 站全是姓氏「田崎」，中文同字形，属误报
           '\u9ebd'      # LCMap 只转到该繁体码点，修复后须归零
           '\u6c88')     # 沈：日文写法（沈黙/沈思），已进 GLYPH_MAP 折叠为沉
           # 円：日文货币字，已由 TERM_FIX 折成「日元」，读数须归零
JP_ONLY += '\u5186'
LATIN = re.compile(r'(?<![A-Za-z])[A-Z]{2,}(?![A-Za-z])')

fixes = {}
for line in (ROOT / 'resource' / 'corpus' / 'review_fixes.jsonl').read_text('utf-8').splitlines():
    e = json.loads(line)
    fixes[(e['script'], e['idx'])] = e['cn']

glyph = collections.Counter()
glyph_rows = collections.defaultdict(list)
latin = collections.Counter()
latin_rows = collections.defaultdict(list)
for line in (ROOT / 'resource' / 'corpus' / 'pairing.jsonl').read_text('utf-8').splitlines():
    r = json.loads(line)
    if r['kind'] not in ('dlg', 'menu', 'flag'):
        continue
    cn = textfix.emit(r['jp'] or '', r['cn'] or '', fixes.get((r['script'], r['idx'])))
    for ch in set(cn) & set(JP_ONLY):
        glyph[ch] += 1
        if len(glyph_rows[ch]) < 6:
            glyph_rows[ch].append((r['script'], r['idx'], cn))
    for m in LATIN.findall(cn):
        latin[m] += 1
        if len(latin_rows[m]) < 4:
            latin_rows[m].append((r['script'], r['idx'], cn))

L = ['# 日式字形与未译外来词', '', '## A. 日式专用汉字（出现次数）']
for ch, n in glyph.most_common():
    L.append(f'- {ch}: {n}')
    for script, idx, cn in glyph_rows[ch]:
        L.append(f'    {script} idx{idx} {cn}')
L += ['', '## B. 拉丁缩略词（出现次数）']
for w, n in latin.most_common():
    L.append(f'- {w}: {n}')
    for script, idx, cn in latin_rows[w]:
        L.append(f'    {script} idx{idx} {cn}')
(ROOT / 'tmp' / 'jp_glyph_scan.md').write_text('\n'.join(L) + '\n', 'utf-8')
print('glyph', ascii(dict(glyph)), 'latin', ascii(dict(latin)))
