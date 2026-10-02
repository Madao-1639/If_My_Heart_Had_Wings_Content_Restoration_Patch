"""用 GB2312 编码可行性反查产物中文里"简体中文标准收不到"的字形。

理由：日式新字体（亜/瀬/対/戸/蛍…）与生僻繁体都不在 GB2312 内，而 LCMapStringW
的繁转简只覆盖繁体、覆盖不到日式字形。逐字判定比手写清单可靠。
命中字需要人工分档：
  - 日式字形 → 加进 tool/textfix.py 的 GLYPH_MAP（零判断，机械替换）；
  - 人名/术语用字（瑠、凪等） → 保留；
  - 需要整句改写的（畳） → 走 pin 层。
结果写 tmp/gb2312_scan.md
"""
import collections
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from tool import fancn  # noqa: E402

hits = collections.Counter()
rows = collections.defaultdict(list)
for name in fancn.script_names():
    for i, t in enumerate(fancn.load_texts(name)):
        if not t:
            continue
        for ch in set(t):
            if not '\u3400' <= ch <= '\u9fff':
                continue
            try:
                ch.encode('gb2312')
            except UnicodeEncodeError:
                hits[ch] += 1
                if len(rows[ch]) < 10:
                    rows[ch].append((name, i, t))

L = ['# GB2312 外接字形（产物口径）', '',
     f'- 命中字数 {len(hits)}，命中行次 {sum(hits.values())}', '']
for ch, n in hits.most_common():
    try:
        ch.encode('gbk')
        gbk = 'GBK有'
    except UnicodeEncodeError:
        gbk = 'GBK也无'
    L.append(f'## {ch} ×{n}（{gbk}）')
    for s, i, t in rows[ch]:
        L.append(f'- {s} idx{i} {t}')
    L.append('')
(ROOT / 'tmp' / 'gb2312_scan.md').write_text('\n'.join(L) + '\n', 'utf-8')
print('chars', len(hits), 'rows', sum(hits.values()))
print(ascii({ch: n for ch, n in hits.most_common()}))
