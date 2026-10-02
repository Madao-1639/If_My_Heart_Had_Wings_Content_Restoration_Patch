"""姓名+敬称的搭配统计，以及句读重复(。。/，，)全库计数。"""
import io
import json
import re
import sys
from collections import Counter

sys.path.insert(0, '.')
from tool import textfix  # noqa: E402

rows = [json.loads(l) for l in open('resource/corpus/pairing.jsonl', encoding='utf-8')]
fixes = {}
for l in open('resource/corpus/review_fixes.jsonl', encoding='utf-8'):
    d = json.loads(l)
    fixes[(d['script'], d['idx'])] = d['cn']


def cn_of(r):
    f = fixes.get((r['script'], r['idx']))
    return textfix.emit(r['jp'] or '', r['cn'] or '', f)


out = io.open('tmp/compounds.md', 'w', encoding='utf-8')
NAMES = ['天音', '碧', '朱莉', '小鸟', '亚纱', '依瑠', '扬羽', '易鸟', '飞冈', '佳奈子', '柾次', '达也']
TITLES = ['学姐', '学长', '前辈', '先辈', '同学', '酱', '姐']
cnt = Counter()
loc = {}
for r in rows:
    cn = cn_of(r)
    for nm in NAMES:
        for t in TITLES:
            if nm + t in cn:
                cnt[nm + t] += 1
                loc.setdefault(nm + t, []).append((r['script'], r['idx']))
out.write('# 姓名+敬称搭配\n\n')
cur = None
for k, v in cnt.most_common():
    nm = k[:2] if not k.startswith('佳奈') else k[:3]
    if nm != cur:
        cur = nm
        out.write(f'\n## {nm}\n')
    out.write(f'- {k}: {v}\n')

# 句读重复
DUP_PUNCT = [('。。', re.compile(r'。。')), ('，，', re.compile(r'，，')),
             ('、、', re.compile(r'、、')), ('………', re.compile(r'…{3,}')),
             ('，。', re.compile(r'，。')), ('。，', re.compile(r'。，'))]
dp = Counter()
dpl = {}
for r in rows:
    cn = cn_of(r)
    for k, rx in DUP_PUNCT:
        if rx.search(cn):
            dp[k] += 1
            dpl.setdefault(k, []).append((r['script'], r['idx'], cn[:60]))
out.write('\n# 句读重复\n')
for k, v in dp.most_common():
    out.write(f'- {k}: {v}\n')
    for s, i, c in dpl[k][:8]:
        out.write(f'    {s} idx{i} {c}\n')

# 残留半角标点/乱码
ODD = [('半角逗号', re.compile(r'[,](?=[^\d])')), ('半角句号结尾', re.compile(r'[a-z\u4e00-\u9fff]\.$')),
       ('问号混用', re.compile(r'\?[？]')), ('乱码?单独', re.compile(r'(?<![a-zA-Z])\?(?![?])')),
       ('●占位', re.compile(r'●')), ('全角空格开头', re.compile(r'^\u3000'))]
od = Counter()
odl = {}
for r in rows:
    cn = cn_of(r)
    for k, rx in ODD:
        if rx.search(cn):
            od[k] += 1
            odl.setdefault(k, []).append((r['script'], r['idx'], cn[:60]))
out.write('\n# 可疑字符\n')
for k, v in od.most_common():
    out.write(f'- {k}: {v}\n')
    for s, i, c in odl[k][:8]:
        out.write(f'    {s} idx{i} {c}\n')
out.close()
print('compounds', len(cnt), 'dup_punct', sum(dp.values()), 'odd', sum(od.values()))
