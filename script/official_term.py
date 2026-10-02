"""两项取证：
  1. 官方 zh-CN（resource/corpus/zh）里关键名词的用字，用来决定民间文本该向哪个写法对齐；
  2. 产物 JSON 里日式专用标点/符号残留（｢｣『』・々｜ 等）。
结果写 tmp/official_term.md
"""
import collections
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from tool import arcbuild, fancn, lng as lng_codec  # noqa: E402

TERMS = ['恵風', '惠风', '恵风', '水瀬', '水濑', '水瀨', '亜紗', '亜纱', '亚纱',
         '風戸', '风戸', '风户', '依瑠', '蛍', '萤', '寮母', '滑空部', '滑翔部',
         '天羽', '小鳥', '小鸟', '揚羽', '扬羽', '佳奈子', '加奈子', '朱莉',
         '易鸟', '哈特', '蛮殻', '蛮壳', '榻榻米', '畳']
off = collections.Counter()
off_sample = collections.defaultdict(list)
# 官方口径必须来自 Steam 官方 zh-CN 归档；resource/corpus/zh 是民汉表的旧提取，不能作证据。
official = {}
failed = []
for name_bytes, data in arcbuild.read_raw(ROOT / 'backup' / 'zh-CN' / 'Rio.arc'):
    name = name_bytes.decode('utf-16le')
    if not name.lower().endswith('.lng'):
        continue
    try:
        official[name.rsplit('.', 1)[0]] = lng_codec.parse_lng(
            data, key=lng_codec.KEY_STEAM_ZHCN)
    except ValueError:
        failed.append(name)

for stem, texts in sorted(official.items()):
    for i, t in enumerate(texts):
        if not t:
            continue
        for term in TERMS:
            if term in t:
                off[term] += t.count(term)
                if len(off_sample[term]) < 3:
                    off_sample[term].append(f'{stem} idx{i} {t[:70]}')

SYMBOL = {'｢': '半角钩括', '｣': '半角钩括', '『': '双钩括', '』': '双钩括',
          '・': '中点', '々': '叠字符', '｜': '全角竖线', 'ー': '长音符',
          '‐': '连字符', '─': '制表线', '▼': '三角', '☆': '星', '─': '线'}
sym_rows = collections.defaultdict(list)
sym_cnt = collections.Counter()
for name in fancn.script_names():
    for i, t in enumerate(fancn.load_texts(name)):
        if not t:
            continue
        for ch in set(t):
            if ch in SYMBOL:
                sym_cnt[ch] += 1
                if len(sym_rows[ch]) < 5:
                    sym_rows[ch].append(f'{name} idx{i} {t[:80]}')

L = ['# 官方用字与日式符号取证', '',
     f'- 官方 zh-CN 解析成功 {len(official)} 个脚本，失败 {len(failed)}：{failed}', '',
     '## 0. 官方 NameTable.txt（人名权威口径）']
for name_bytes, data in arcbuild.read_raw(ROOT / 'backup' / 'zh-CN' / 'Rio.arc'):
    if name_bytes.decode('utf-16le') == 'NameTable.txt':
        L += [x for x in data.decode('utf-8', 'replace').splitlines()]
        break
L += ['', '## 1. 官方 zh-CN 关键名词']
for term in TERMS:
    L.append(f'- {term}: {off.get(term, 0)}')
    for s in off_sample[term]:
        L.append(f'    {s}')
L += ['', '## 2. 产物里的日式符号']
for ch, n in sym_cnt.most_common():
    L.append(f'- {ch}（{SYMBOL[ch]}）×{n}')
    for s in sym_rows[ch]:
        L.append(f'    {s}')
(ROOT / 'tmp' / 'official_term.md').write_text('\n'.join(L) + '\n', 'utf-8')
print('official', ascii({k: v for k, v in off.items() if v}))
print('symbols', ascii(dict(sym_cnt)))
