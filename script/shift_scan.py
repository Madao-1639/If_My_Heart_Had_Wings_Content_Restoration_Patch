"""译文列错位（shift）候选窗口探测：只看结构代理，语义判定交人工/评审。

背景：民汉表里存在**汉化组自己**造成的错位——某个窗口内第 k 条的中文其实是第
k+1 行日文的译文（表内键值仍与日文行一一相等，所以按 CRC32 校验查不出来，
只有读语义才发现）。这类错位会让上屏台词整体前移一句。

两个结构代理（都只提名候选，不判定）：
  L 长度位移：译文长度正比于原文长度。若某槽中文与**邻行**日文的长度关系明显
    好于与**本行**，则该行属于位移段。合并连续疑似槽为窗口。
  Q 引号形状：对白用 `「」`、旁白不用；连续错配也是位移特征。
"""
import collections
import io
import json
import math
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from tool import fancn  # noqa: E402

OUT = ROOT / 'tmp' / 'shift_scan.md'
MINLEN = 6          # 太短的行长度信息量不足，不参与位移判定
DEV_ABS = 0.45      # 本行对数偏差要大到这个程度才提名
REL = 0.5           # 邻行偏差需优于本行偏差的这个比例


def core(text):
    t = re.sub(r'%[A-Za-z0-9]+', '', text or '')
    t = re.sub(r'[\s「」『』〈〉《》（）()［］【】。．、，,：:；;！!？?\.\-—―~～＋+＊*ー〜…＼\\]+',
               '', t)
    return t


def dev(cn, jp):
    a, b = len(core(cn)), len(core(jp))
    if b < MINLEN or a == 0:
        return None
    return abs(math.log(a / b))


def shape(text):
    t = (text or '').strip()
    c = re.sub(r'%[A-Za-z0-9]+', '', t)
    if not c.strip():
        return 'empty'
    if not re.search(r'「', c):
        return 'narr'
    return 'quote' if c.startswith('「') else 'mixed'


def main():
    rows = collections.defaultdict(dict)
    for l in (ROOT / 'resource' / 'corpus' / 'pairing.jsonl').read_text('utf-8').splitlines():
        r = json.loads(l)
        if r['kind'] == 'dlg' and r['idx'] is not None:
            rows[r['script']][r['idx']] = r

    prod = {name: fancn.load_map(name) for name in fancn.script_names()}
    cand_L, cand_Q = [], []
    for name in sorted(rows):
        got = prod.get(name, {})
        idxs = sorted(rows[name])
        jp = [rows[name][i]['jp'] for i in idxs]
        cn = [got.get(i, '') for i in idxs]
        susp = set()
        for k in range(1, len(idxs) - 1):
            d0 = dev(cn[k], jp[k])
            dp = dev(cn[k], jp[k + 1])
            dm = dev(cn[k], jp[k - 1])
            if d0 is None or d0 < DEV_ABS:
                continue
            if dp is not None and dp < d0 * REL:
                susp.add(idxs[k])
            elif dm is not None and dm < d0 * REL:
                susp.add(idxs[k])
        for i in sorted(susp):
            cand_L.append((name, i))
        # 引号形状错配（含孤立槽）作辅助线索
        for k in range(len(idxs)):
            sj, sc = shape(jp[k]), shape(cn[k])
            if (sj, sc) in (('quote', 'narr'), ('narr', 'quote')):
                cand_Q.append((name, idxs[k]))

    def cluster(items):
        by = collections.defaultdict(list)
        for name, i in items:
            by[name].append(i)
        runs = []
        for name, v in by.items():
            v.sort()
            start = prev = v[0]
            for i in v[1:]:
                if i == prev + 1:
                    prev = i
                    continue
                runs.append((name, list(range(start, prev + 1))))
                start = prev = i
            runs.append((name, list(range(start, prev + 1))))
        return runs

    runs_L, runs_Q = cluster(cand_L), cluster(cand_Q)
    out = io.open(OUT, 'w', encoding='utf-8')
    out.write('# 译文列错位候选窗口（结构代理，只提名不判定）\n\n')
    out.write(f'## L 长度位移：窗口 {len(runs_L)}，涉及槽位 {len(cand_L)}\n\n')
    out.write(f'## Q 引号形状错配（辅助）：槽位 {len(cand_Q)}\n\n')
    for name, run in runs_L:
        got = prod[name]
        idxs = sorted(rows[name])
        pos = idxs.index(run[0])
        span = idxs[max(0, pos - 2):min(len(idxs), idxs.index(run[-1]) + 3)]
        out.write(f'### L {name} 疑似 {run[0]}…{run[-1]}（{len(run)}）\n')
        for i in span:
            r = rows[name][i]
            final = got.get(i, '')
            tag = '>>' if i in run else '  '
            d0 = dev(final, r['jp'])
            out.write(f'{tag} idx{i} 形JP={shape(r["jp"])}/形CN={shape(final)}'
                      f' dev0={d0 if d0 is None else round(d0, 2)}\n')
            out.write(f'    JP {r["jp"]}\n    CN {final}\n')
        out.write('\n')
    out.close()
    print('runs_L', len(runs_L), 'slots_L', len(cand_L),
          'clash_Q_slots', len(cand_Q), 'runs_Q', len(runs_Q))


if __name__ == '__main__':
    main()

