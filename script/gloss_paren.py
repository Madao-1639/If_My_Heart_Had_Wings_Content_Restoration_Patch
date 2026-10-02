"""扫描"日文侧没有圆括号、中文侧凭空多出圆括注"的行，并按内容分档。

这类行的共同形态是：民汉把日文拟声词/动作声直接译成"（动作）"或"（声音）"，
括注里塞的是解说而不是正文；也有的是日文用破折号 ―― 作同位语，中文改写成括注。
现有判据只看"中文括注数量 > 日文括注数量"，会漏掉日文整行没有括号的情形，
所以这里按"日文完全没有圆括号"来筛，覆盖面更全。只读产物，不改数据。

分档：
  A 拟声/动作被写成括注（括注就是整行内容）——必须改写成正文，不能只删括号；
  B 解释词义的旁注（日文侧无对应内容）——删除或改写；
  C 日文本身用破折号 ―― 引出同位语，中文改用括注——可接受，人工确认。
C 档只认破折号：顿号 、 不构成把解说塞进括注的理由，否则「(啾)、(啾)」这类
凭空括注会被误判成可接受（旧判据就是这样漏掉的）。
"""
import io
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from tool import textfix  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent

JP_PAREN = re.compile(r'[（(［【]')
CN_PAREN = re.compile(r'[（(][^（()）]{1,24}[）)]')
FLOW = re.compile(r'%K|%P')
QUOTER = re.compile(r'[「」『』]')

def collect():
    """返回 (A, B, C) 三档行列表；判据只在这里定义一次，供复检与批次生成共用。"""
    fixes = {}
    for l in (ROOT / 'resource' / 'corpus' / 'review_fixes.jsonl').read_text('utf-8').splitlines():
        d = json.loads(l)
        fixes[(d['script'], d['idx'])] = d['cn']

    rows = []
    for l in (ROOT / 'resource' / 'corpus' / 'pairing.jsonl').read_text('utf-8').splitlines():
        r = json.loads(l)
        if r['kind'] == 'name':
            continue
        jp = r['jp'] or ''
        if JP_PAREN.search(jp):
            continue
        cn = textfix.emit(jp, r.get('cn') or '', fixes.get((r['script'], r['idx'])))
        if not CN_PAREN.search(cn):
            continue
        # 去掉括注后还剩正文的，属"补注"；整行只剩括注的，属"拟声/动作被括起来"
        rest = CN_PAREN.sub('', FLOW.sub('', cn))
        # 连字符在字符类里必须转义或置于首尾，否则会被解析成区间
        rest = re.sub('[\\s！？。、…—―・~〜〜ー\'\"()（）「」『』.,!?:;\\-]', '', rest)
        rows.append({'script': r['script'], 'idx': r['idx'], 'kind': r['kind'],
                     'jp': jp, 'cn': cn, 'bare': not rest})

    a = [r for r in rows if r['bare']]
    c = [r for r in rows
         if not r['bare'] and ('――' in r['jp'] or '―' in r['jp'] or '—' in r['jp'])]
    b = [r for r in rows if not r['bare'] and r not in c]
    return a, b, c


if __name__ == '__main__':
    a, b, c = collect()
    L = ['# 日文无括号、中文多出括注的行', '',
         f'- 合计 {len(a) + len(b) + len(c)}',
         f'- A 括注即整行内容（拟声/动作被括起来，必须改写）：{len(a)}',
         f'- B 正文外的补注（日文侧无对应内容，多为解释）：{len(b)}',
         f'- C 日文用破折号/顿号做同位语，中文改写成括注（可接受）：{len(c)}', '']
    for title, items in (('A', a), ('B', b), ('C', c)):
        L.append(f'## 档 {title}')
        for r in items:
            L.append(f"- {r['script']} idx{r['idx']}")
            L.append(f"    JP {r['jp']}")
            L.append(f"    CN {r['cn']}")
        L.append('')
    (ROOT / 'tmp' / 'gloss_paren.md').write_text('\n'.join(L) + '\n', 'utf-8')
    print('total', len(a) + len(b) + len(c), 'A', len(a), 'B', len(b), 'C', len(c))
