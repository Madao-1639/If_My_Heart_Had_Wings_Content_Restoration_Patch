"""统计产物 JSON 里"民间用词 vs 官方用词"的分布，为跨源一致性决策提供数据。

对照项取自官方 zh-CN 的权威写法（tmp/official_term.md）：
  滑翔部/滑翔机社、寮母/管理员、寮/宿舍、部室/活动室、部员/社员…
只读；结果写 tmp/term_gap.md
"""
import collections
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from tool import fancn  # noqa: E402

TERMS = ['\u60e0\u98ce\u5b66\u56ed', '\u60e0\u98ce\u5b66\u9662', '\u6075\u98ce\u5b66\u9662', '滑翔部', '滑空部', '飞行部', '寮母', '寮', '部室', '活动室的', '部员',
         '社员', '机库', '车库', '滑翔机', '滑翔机社', '惠风', '恵风',
         '水濑', '水瀬', '亚纱', '亜纱', '风户', '风戸', '萤', '蛍',
         '前辈', '社长', '会长', 'administrator']

cnt = collections.Counter()
sample = collections.defaultdict(list)
per_script = collections.defaultdict(collections.Counter)
for name in fancn.script_names():
    for i, t in enumerate(fancn.load_texts(name)):
        if not t:
            continue
        for term in TERMS:
            n = t.count(term)
            if n:
                cnt[term] += n
                per_script[name][term] += n
                if len(sample[term]) < 6:
                    sample[term].append((name, i, t[:90]))

L = ['# 民间用词分布（产物口径）', '']
for term, n in cnt.most_common():
    scripts = [s for s in per_script if term in per_script[s]]
    L.append(f'## {term} ×{n}｜脚本数 {len(scripts)}')
    for s, i, t in sample[term]:
        L.append(f'- {s} idx{i} {t}')
    L.append('')
(ROOT / 'tmp' / 'term_gap.md').write_text('\n'.join(L) + '\n', 'utf-8')
print(ascii(dict(cnt)))
