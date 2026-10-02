"""官方 zh-CN 侧的符号与词选用法取证（决定民间文本要对齐哪些）。

查三件事：
  1. 『』 ｢｣ ・ 々 在官方中文里是否使用；
  2. 寮母 / 寮 / 部室 在官方中文里的对应词（管理员？宿舍？活动室？）；
  3. 官方对应行的原文，用来核对民间译法的语义是否走偏。
结果写 tmp/official_symbol.md
"""
import collections
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from tool import arcbuild, lng as lng_codec  # noqa: E402

SYMS = ['『', '』', '｢', '｣', '・', '々', '｜', 'ー']
WORDS = ['寮母', '寮', '部室', '活动室', '管理员', '宿舍', '社长', '部长', '社员', '部员']

official = {}
for name_bytes, data in arcbuild.read_raw(ROOT / 'backup' / 'zh-CN' / 'Rio.arc'):
    name = name_bytes.decode('utf-16le')
    if not name.lower().endswith('.lng'):
        continue
    try:
        official[name.rsplit('.', 1)[0]] = lng_codec.parse_lng(
            data, key=lng_codec.KEY_STEAM_ZHCN)
    except ValueError:
        official[name.rsplit('.', 1)[0]] = None

sym = collections.Counter()
word = collections.Counter()
sample = collections.defaultdict(list)
parsed = 0
for stem, texts in sorted(official.items()):
    if texts is None:
        continue
    parsed += 1
    for i, t in enumerate(texts):
        if not t:
            continue
        for ch in SYMS:
            if ch in t:
                sym[ch] += t.count(ch)
        for w in WORDS:
            n = t.count(w)
            if n:
                word[w] += n
                if len(sample[w]) < 6:
                    sample[w].append((stem, i, t[:80]))

L = [f'# 官方符号与词选（解析成功 {parsed} 个脚本）', '', '## 符号']
L += [f'- {ch} ×{n}' for ch, n in sym.most_common()] or ['- 无']
L += ['', '## 词选']
for w, n in word.most_common():
    L.append(f'## {w} ×{n}')
    for s, i, t in sample[w]:
        L.append(f'- {s} idx{i} {t}')
    L.append('')
(ROOT / 'tmp' / 'official_symbol.md').write_text('\n'.join(L) + '\n', 'utf-8')
print('sym', ascii(dict(sym)))
print('word', ascii(dict(word)))
