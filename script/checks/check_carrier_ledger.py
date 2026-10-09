# -*- coding: utf-8 -*-
"""承载图 × 判读台账 **只读对账**（2026-10-08）。

用法：
    python script/checks/check_carrier_ledger.py [--content-scan] [--out tmp/carrier_ledger_check.md]

三部分：
  A 覆盖对账：每条台账条目的 `block_orig`/`block_steam` 闭区间必须能被承载图的块**拼出**
    （可跨多块，但不许越出承载图覆盖或跨缝）。分三类落账：
      - exact   ：区间与某个承载图块逐字相等
      - span    ：跨了相邻多块的并集（覆盖一致，仅边界不同）——记账，不报警
      - ALARM   ：覆盖断裂/越界 —— **报警（退出码 1）**
  B 已知假锚/拆行：`resource/carrier_quirks.json` 逐条核对
      - 机械配对是否仍在承载图上（不在 ⇒ STALE：本表该条可退休，仅提示）
      - 台账动作是否已落地（未落 ⇒ UNFIXED：**报警（退出码 1）**）
  C 内容面候选（`--content-scan`，只报告不报警）：原版行民汉 vs Steam 槽官中的**同中文**字符相似度低
    （`ratio < 0.18` 或字符集 Jaccard < 0.12，且较短者 ≥6 字 —— 与 2026-10-08 锚点抽查同口径）
    ⇒ 列出人工需读的候选（假锚类别里机器唯一能自动再发现的信号，见 doc/restoration-targets.md）。

只读：不改任何 resource/ 文件。明细写 `--out`（默认 tmp/carrier_ledger_check.md），控制台只输出 ASCII 摘要。
退出码：0 = 无 ALARM / 无 UNFIXED；1 = 有。
"""
import argparse
import collections
import glob
import json
import os
import sys
import difflib

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
from tool import v5lib  # noqa: E402

CARRIER = os.path.join(ROOT, 'resource', 'carrier_map.json')
QUIRKS = os.path.join(ROOT, 'resource', 'carrier_quirks.json')
ADJ = os.path.join(ROOT, 'resource', 'adjudication')
PLAN = os.path.join(ROOT, 'resource', 'restore_plan.json')
TH = 0.34   # 仅 Part C 的宽松参考；实际判据见 main 内的 ratio/Jaccard 严口径


def rng(a, b):
    return set(range(a, b + 1)) if b >= a else set()


def seg_cover(blocks, side, lo, hi):
    """承载图在该侧对闭区间 [lo,hi] 的覆盖是否连续且完整。"""
    segs = []
    for b in blocks:
        r = b.get(side)
        if not r:
            continue
        if r[1] < lo or r[0] > hi:
            continue
        segs.append((max(r[0], lo), min(r[1], hi)))
    segs.sort()
    cur = lo - 1
    broken = False
    for a, b2 in segs:
        if a > cur + 1:
            broken = True
        cur = max(cur, b2)
    return cur >= hi and not broken


def load_ledgers():
    led = collections.defaultdict(list)
    for p in sorted(glob.glob(os.path.join(ADJ, '*.jsonl'))):
        s = os.path.basename(p)[:-6]
        if s.startswith('rereview'):
            continue
        for line in open(p, encoding='utf-8'):
            if line.strip():
                led[s].append(json.loads(line))
    return led


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--content-scan', action='store_true')
    ap.add_argument('--out', default=os.path.join(ROOT, 'tmp', 'carrier_ledger_check.md'))
    a = ap.parse_args()

    car = v5lib.carrier()
    led = load_ledgers()
    plan = json.load(open(PLAN, encoding='utf-8'))
    L = ['# 承载图 × 台账 只读对账', '']

    # ── A 覆盖对账
    exact = span = 0
    alarms = []
    for s, es in led.items():
        blocks = car[s]['blocks']
        keys = {(tuple(b['orig']) if b.get('orig') else None,
                 tuple(b['steam']) if b.get('steam') else None) for b in blocks}
        for e in es:
            o, k = e.get('block_orig'), e.get('block_steam')
            ok_o = (not o) or o[1] < o[0] or seg_cover(blocks, 'orig', o[0], o[1])
            ok_k = (not k) or k[1] < k[0] or seg_cover(blocks, 'steam', k[0], k[1])
            if not (ok_o and ok_k):
                alarms.append((s, e.get('id'), o, k, ok_o, ok_k))
                continue
            key = ((tuple(o) if o and o[1] >= o[0] else None),
                   (tuple(k) if k and k[1] >= k[0] else None))
            if key in keys:
                exact += 1
            else:
                span += 1
                L.append('- span（跨块合并，覆盖一致）：`%s` id=%s orig=%s steam=%s'
                         % (s, e.get('id'), o, k))
    L.insert(2, '- A 覆盖对账：exact %d / span %d / ALARM %d' % (exact, span, len(alarms)))
    L.insert(3, '')
    for x in alarms:
        L.append('- **ALARM** `%s` id=%s orig=%s steam=%s ok_orig=%s ok_steam=%s' % x)

    # ── B 已知假锚/拆行
    qk = json.load(open(QUIRKS, encoding='utf-8'))
    stale, unfixed, okn = [], [], 0
    for q in qk['quirks']:
        s = q['script']
        mo, ms = q['mechanical']['orig'], q['mechanical']['steam']
        present = False
        for b in car[s]['blocks']:
            o, k = b.get('orig'), b.get('steam')
            if not o or not k:
                continue
            for r in range(mo[0], mo[1] + 1):
                kk = k[0] + (r - o[0])
                if o[0] <= r <= o[1] and kk == ms[0] and b['kind'] in ('anchor', 'match'):
                    present = True
        if not present:
            stale.append(q)
            continue
        rule = q['ledger_rule']
        p = plan['hosts'].get(s, {}).get('plan', {})
        tov = p.get('text_overrides', {})
        ins_rows = set()
        for _, r0, r1 in p.get('inserts', []):
            ins_rows |= rng(r0, r1)
        good = True
        if rule == 'slot_dropped':
            good = ms[0] in set(p.get('drops', []))
        elif rule == 'text_override':
            good = (str(ms[0]) in tov) and (tov.get(str(ms[0])) != mo[0])
        elif rule == 'row_inserted':
            good = any(r in ins_rows for r in rng(mo[0], mo[1]))
        if good:
            okn += 1
        else:
            unfixed.append(q)
    L.append('')
    L.append('- B 已知假锚/拆行：OK %d / STALE %d / UNFIXED %d（表 `resource/carrier_quirks.json`）'
             % (okn, len(stale), len(unfixed)))
    for q in stale:
        L.append('- STALE（承载图上已无此机械配对，本表该条可退休）：`%s` %s %s'
                 % (q['script'], q['kind'], q['mechanical']))
    for q in unfixed:
        L.append('- **UNFIXED**（台账动作未落地）：`%s` %s %s rule=%s ledger=%s'
                 % (q['script'], q['kind'], q['mechanical'], q['ledger_rule'], q['ledger']))

    # ── C 内容面候选（只报告）
    ncand = 0
    if a.content_scan:
        zh = v5lib.lng_official()
        sys.path.insert(0, os.path.join(ROOT, 'tmp'))
        import vos_dump
        tov_all = {(s, int(k)) for s, h in plan['hosts'].items()
                   for k in (h.get('plan') or {}).get('text_overrides', {})}
        quirk_sites = {(q['script'], q['mechanical']['orig'][0], q['mechanical']['steam'][0])
                       for q in qk['quirks']}
        L.append('')
        L.append('- C 内容面候选（民汉 vs 官中，ratio<0.18 或 Jaccard<0.12，≥6 字；只报告）')
        for s, z in sorted(zh.items()):
            if s not in car:
                continue
            for b in car[s]['blocks']:
                if b['kind'] != 'anchor':      # 与锚点抽查同口径：只扫 anchor（match 由 §41/§49 复审覆盖）
                    continue
                o0, o1 = b['orig']
                k0, k1 = b['steam']
                for j in range(min(o1 - o0, k1 - k0) + 1):
                    o, k = o0 + j, k0 + j
                    if (s, o, k) in quirk_sites or (s, k) in tov_all:
                        continue
                    f = (vos_dump.fan(s, o) or '').replace('%K', '').replace('%P', '').strip()
                    zz = (z[k] if k < len(z) else '').replace('%K', '').replace('%P', '').strip()
                    if not f or not zz or min(len(f), len(zz)) < 6:
                        continue
                    r = difflib.SequenceMatcher(None, f, zz).ratio()
                    A_, B_ = set(f), set(zz)
                    j = len(A_ & B_) / max(1, len(A_ | B_))
                    if r < 0.18 or j < 0.12:
                        ncand += 1
                        L.append('  - `%s` o%d/s%d 民汉=%s ｜ 官中=%s' % (s, o, k, f[:30], zz[:30]))

    with open(a.out, 'w', encoding='utf-8', newline='\n') as f:
        f.write('\n'.join(L) + '\n')
    print('A exact %d / span %d / ALARM %d ; B OK %d / STALE %d / UNFIXED %d%s'
          % (exact, span, len(alarms), okn, len(stale), len(unfixed),
             ' ; C candidates %d' % ncand if a.content_scan else ''))
    print('report:', os.path.relpath(a.out, ROOT))
    for x in alarms:
        print('  ALARM', x[0], x[1], x[2], x[3])
    for q in unfixed:
        print('  UNFIXED', q['script'], q['kind'], q['mechanical'])
    sys.exit(1 if (alarms or unfixed) else 0)


if __name__ == '__main__':
    main()
