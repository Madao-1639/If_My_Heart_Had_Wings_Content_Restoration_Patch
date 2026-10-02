"""从**产物 JSON**（`resource/fan_cn/{SCRIPT}.json`）回读，检查残留的译者批注、日文货币字、以及点名行的数字疑点。

只统计/取样，不改数据；结果写 tmp/built_defects.md。
"""
import collections
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from tool import fancn  # noqa: E402

PAIR = {}
for line in (ROOT / 'resource' / 'corpus' / 'pairing.jsonl').read_text('utf-8').splitlines():
    r = json.loads(line)
    if r['kind'] == 'dlg' and r['idx'] is not None:
        PAIR.setdefault(r['script'], {})[r['idx']] = r

RX = {
    'note-star': re.compile(r'[＊*]\s*注[：:]|^\s*注[：:]'),
    'note-bracket': re.compile(r'[（(][^（()）]{0,10}?(?:捏他|注|梗|即|原文)[^（()）]{4,}[）)]'),
    'yen-variant': re.compile(r'(?<=[0-9０-９])[ \t]*(?:日圆|日元|圆)'),
    'placeholder': re.compile(r'[●□■◎＿]{2,}|TODO|待补|待译'),
    'translator-word': re.compile(r'译者|翻译注|原文是'),
    'kana-leftover': re.compile(r'[぀-ヿｦ-ﾟ]'),
    'fullwidth-leftover': re.compile(r'[０-９Ａ-Ｚａ-ｚ]'),
    # 合法的反斜杠只有软换行 \n；多出来一个（\\n）会原样上屏
    'stray-backslash': re.compile(r'\\(?!n)'),
}
INFO = {
    'bare-number': re.compile(r'\d{4,}(?![\d米秒日韩年公里台])'),
}
hits = collections.defaultdict(list)
info = collections.defaultdict(list)
yen_total = 0
counts = collections.Counter()

for script in fancn.script_names():
    texts = fancn.load_texts(script)
    for idx, t in enumerate(texts):
        if not t:
            continue
        jp = (PAIR.get(script, {}).get(idx) or {}).get('jp', '')
        for tag, rx in RX.items():
            if rx.search(t):
                hits[tag].append((script, idx, jp[:70], t[:90]))
                counts[tag] += 1
        for tag, rx in INFO.items():
            if rx.search(t):
                info[tag].append((script, idx, jp[:70], t[:90]))
        yen_total += t.count('円')

L = ['# 产物残留缺陷扫描', '',
     '- 缺陷命中：' + (', '.join(f'{k} {v}' for k, v in counts.most_common()) or '无'),
     '- 参考项（非缺陷）：' + ', '.join(f'{k} {len(v)}' for k, v in info.items()),
     f'- 货币单位：「円」{yen_total} 次，未归一写法 {len(hits["yen-variant"])} 处', '']
for tag, rows in hits.items():
    L.append(f'## {tag}（{len(rows)}）')
    for s, i, jp, cn in rows[:30]:
        L.append(f'- {s} idx{i}')
        L.append(f'    JP {jp}')
        L.append(f'    CN {cn}')
    L.append('')
for tag, rows in info.items():
    L.append(f'## [info] {tag}（{len(rows)}）')
    for s, i, jp, cn in rows[:30]:
        L.append(f'- {s} idx{i}')
        L.append(f'    JP {jp}')
        L.append(f'    CN {cn}')
    L.append('')
(ROOT / 'tmp' / 'built_defects.md').write_text('\n'.join(L) + '\n', 'utf-8')
print('hits', dict(counts), 'yen', yen_total)
