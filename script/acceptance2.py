"""补充验收：空槽位统计、长重复中文、疑似错字全库计数。"""
import io
import json
import re
import sys
from collections import Counter

sys.path.insert(0, '.')
sys.path.insert(0, 'script')
from tool import fancn  # noqa: E402
from tool import textfix  # noqa: E402

rows = [json.loads(l) for l in open('resource/corpus/pairing.jsonl', encoding='utf-8')]
fixes = {}
for l in open('resource/corpus/review_fixes.jsonl', encoding='utf-8'):
    d = json.loads(l)
    fixes[(d['script'], d['idx'])] = d['cn']
by_script = {}
for r in rows:
    by_script.setdefault(r['script'], []).append(r)
FLOW = re.compile(r'%K|%P|\\n')

out = io.open('tmp/acceptance2.md', 'w', encoding='utf-8')

# A. 空槽位：产物里存在但配对表没有内容的槽（引擎只有被脚本引用才显示）
tot_slots = tot_empty = 0
worst = []
for name in sorted(by_script):
    back = fancn.load_texts(name)
    covered = {r['idx'] for r in by_script[name]}
    empt = [i for i, s in enumerate(back) if not FLOW.sub('', s).strip()]
    uncovered_empty = [i for i in empt if i not in covered]
    covered_empty = [i for i in empt if i in covered]
    tot_slots += len(back)
    tot_empty += len(empt)
    if covered_empty:
        worst.append((name, covered_empty[:10]))
out.write('# 补充验收\n\n## A. 槽位覆盖\n')
out.write(f'- 槽位总数 {tot_slots}，内容为空 {tot_empty}\n')
out.write(f'- 有配对行却内容为空的脚本：{len(worst)}\n')
for name, lst in worst:
    out.write(f'  - {name}: {lst}\n')

# B. 长中文重复（>=10 字，出现在 >=2 个槽位）：错位的强信号
share = Counter()
where = {}
for r in rows:
    if r['kind'] not in ('dlg', 'flag', 'menu'):
        continue
    c = textfix.emit(r['jp'], r['cn'], fixes.get((r['script'], r['idx'])))
    core = FLOW.sub('', c).strip('「」『』“” …—－-、，。！?？~')
    if len(core) < 10:
        continue
    share[core] += 1
    where.setdefault(core, []).append((r['script'], r['idx'], r['jp']))
out.write('\n## B. 长句重复（core>=10 字）\n')
n = 0
for c, k in share.most_common():
    if k < 2:
        break
    n += 1
    out.write(f'- {k}x  {c}\n')
    for s, i, jp in where[c][:6]:
        out.write(f'    {s} idx{i} JP {jp}\n')
out.write(f'- 合计 {n} 组\n')

# C. 疑似错字/用语全库计数
TYPOS = ['幸苦', '赖害', '小小鸟', '内卷', '拉满', '上头', '破防', '贴春联',
         '加奈子', '易香', '吉莉', '学姐', '先辈', '游ば']
cnt = Counter()
loc = {}
for r in rows:
    c = textfix.emit(r['jp'], r['cn'], fixes.get((r['script'], r['idx'])))
    for t in TYPOS:
        if t in c:
            cnt[t] += 1
            loc.setdefault(t, []).append((r['script'], r['idx'], c[:70]))
out.write('\n## C. 疑点计数\n')
for t in TYPOS:
    out.write(f'- {t}: {cnt[t]}\n')
    for s, i, c in loc.get(t, [])[:6]:
        out.write(f'    {s} idx{i} {c}\n')
out.close()
print('empty_slots', tot_empty, 'covered_empty_scripts', len(worst),
      'long-dup-groups', n)
