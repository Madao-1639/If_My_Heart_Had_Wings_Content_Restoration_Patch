# -*- coding: utf-8 -*-
"""CG 显示序列对比：原版 CG 显示序列 vs 产物 CG 显示序列（按名、按序）。

不依赖行对行映射：两侧的 CG 显示序列在忠实还原下应当**逐项同名同序**。
用 difflib 在名字序列上求 opcode，列出 missing / extra / replaced，并带相邻台词定位。
"""
import bisect
import json
import os
import re
import sys
import difflib
import collections

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
from tool import v5lib, ws2, arcbuild, scriptext  # noqa: E402

PNG = re.compile(rb'\x33([A-Za-z0-9_]{2,12})\x00([A-Za-z0-9_.\-]+\.PNG)\x00', re.I)
OUT = os.path.join(ROOT, 'tmp', '_q_cg_seq.md')


def seq_of(raw, script):
    """逐行 CG 显示序列 → `[(行序, [(通道, 图名), ...])]`。

    ⚠️ **每行记录全部 `.PNG` 显示，不只第一张**：旧实现用 `seen.setdefault(k, ...)`，
    同一行只留首张 ⇒ 与 `ev` 同行的「CG 名图挂在 `bg*/st*` 通道」永远不会进本闸
    （实测产物有 2,031 行含多张 `.PNG`、被丢弃 3,176 张；其中「CG 名图挂 `st*/bg*`」的
    211 处落在「perfsync 按图名豁免」与「本闸只取首张」两条线的缝里，无人审）。
    改为按 **`(行, 通道)`** 记录：同一通道同一行只取最后一张（后者覆盖前者，与引擎末值语义一致），
    不同通道各自保留——这样「按槽定罪」的判据才能看到全部通道。
    """
    dec = ws2.decode(raw)
    rl = [r for r in scriptext.script_rows(script, raw) if r['kind'] in ('dlg', 'ctrl')]
    offs = [r['off'] for r in rl]
    per_row = {}
    for m in PNG.finditer(dec):
        k = bisect.bisect_right(offs, m.start())
        if k >= len(rl):
            continue
        chan = m.group(1).decode('cp932', 'replace') if m.group(1) else '?'
        name = m.group(2).decode('ascii', 'replace').upper()
        per_row.setdefault(k, {})[chan] = name      # 同通道末值覆盖；不同通道并存
    return [(k, sorted(v.items())) for k, v in sorted(per_row.items())], rl


def series(n):
    """CG 系列键：`<角色>_<场景>`（如 AGE_06 / KOT_12 / AMA_09）；背景名返回 None。"""
    if not n or not is_cg(n):
        return None
    m = re.match(r'^([A-Z0-9]{2,5}_\d{2,4})_', n.upper())
    return m.group(1) if m else n.upper()


ROUTES = {'AGE', 'AMA', 'ASA', 'CO1', 'CO2', 'HUT', 'KOT', 'YOR'}   # 路线/场景代码 = Rio.arc 脚本名前缀（doc/pna-resources.md）


def is_cg(n):
    """**权威口径（与 tool/perfsync.is_cg_name 一致）**：CG = 名字形如 `{路线名}_{编号}`（`AGE_06_001S`、`KOT_12_003B`）；
    其余（`BG*`/`SKY*`/`EST_*`/`CUTIN_*`/`COM_*`/`ST*`/`IMD*`/`MOS*`）为**其他素材**（背景/立绘/转场），不入本判据。"""
    if not n:
        return False
    u = n.upper()
    return (u.split('_')[0] in ROUTES
            and bool(re.match(r'^[A-Z]{3}_\d{2,4}(_\d{2,4}[A-Z]?)?\.PNG$', u)))


def main():
    plan = json.load(open(os.path.join(ROOT, 'resource', 'restore_plan.json'), encoding='utf-8'))
    prod = {}
    for nb, d in arcbuild.read_raw(os.path.join(ROOT, 'asset', 'Rio.arc')):
        n = nb.decode('utf-16le', 'replace')
        if n.lower().endswith('.ws2'):
            prod[n[:-4].upper()] = d
    car = v5lib.carrier()
    rep = []
    tot = collections.Counter()
    detail = []
    for s in sorted(prod):
        if s not in car:
            continue
        o_all, o_rl = seq_of(v5lib.rio('orig')[s], s)
        p_all, p_rl = seq_of(prod[s], s)
        # 取 CG 名图的条目：`seq_of` 现在返回 `(行, [(通道, 图名), ...])`，
        # 每行可能有多张（含 `bg*/st*` 通道上的 CG名图）——**全部保留**，只过滤非 CG 名。
        o_cg = [(k, ch, v) for k, items in o_all for ch, v in items if is_cg(v)]
        p_cg = [(k, ch, v) for k, items in p_all for ch, v in items if is_cg(v)]
        # 序列按**图名**比（与原实现同口径）；通道信息保留在条目里供报告定位。
        on = [v for _, _, v in o_cg]
        pn = [v for _, _, v in p_cg]
        if on == pn:
            continue
        sm = difflib.SequenceMatcher(a=on, b=pn, autojunk=False)
        for tag, i1, i2, j1, j2 in sm.get_opcodes():
            if tag == 'equal':
                continue
            tot[tag] += 1
            o_part = o_cg[i1:i2]
            p_part = p_cg[j1:j2]
            os_ = {series(v) for _, _, v in o_part if series(v)}
            ps_ = {series(v) for _, _, v in p_part if series(v)}
            def ctx(lst, i, j):
                # 该段在某一侧的上下文系列：段前的最后一条（没有则段后的第一条）
                for k in range(i - 1, -1, -1):
                    if series(lst[k][2]):
                        return series(lst[k][2])
                for k in range(j, len(lst)):
                    if series(lst[k][2]):
                        return series(lst[k][2])
                return None
            if os_ and ps_:
                same = os_ == ps_
            elif ps_ and not os_:
                same = ctx(o_cg, i1, i2) in ps_
            elif os_ and not ps_:
                same = ctx(p_cg, j1, j2) in os_
            else:
                same = True
            tot['同系列' if same else '异系列'] += 1
            rep.append('- **%s %s** %s 原版 %s ↔ 产物 %s'
                       % (s, tag, '（同系列·版本差异）' if same else '（**异系列/类别级 ⇒ 缺陷候选**）',
                          o_part or '—', p_part or '—'))
            detail.append((s, tag, o_part, p_part, o_rl, p_rl))
    L = ['# CG 显示序列对比（原版 vs 产物，按名按序）', '',
         '- 差异段 %d（%s）' % (len(rep), dict(tot)), ''] + rep + ['', '## 差异段相邻台词（定位用）', '']
    for s, tag, o_part, p_part, o_rl, p_rl in detail:
        L.append('### %s · %s' % (s, tag))
        L.append('')
        L.append('- 原版：%s' % (o_part or '—'))
        for k, ch, v in o_part:
            L.append('  - o%d [%s] `%s` ｜ 前文 o%d：%s' % (k, ch, v, max(0, k - 1), (o_rl[k - 1]['jp'] or '')[:44] if k - 1 < len(o_rl) else ''))
            L.append('  - 本行 o%d：%s ｜ 后文 o%d：%s' % (k, (o_rl[k]['jp'] or '')[:44], min(len(o_rl) - 1, k + 1),
                                                    (o_rl[k + 1]['jp'] or '')[:44] if k + 1 < len(o_rl) else ''))
        L.append('- 产物：%s' % (p_part or '—'))
        for k, ch, v in p_part:
            L.append('  - 产物行 %d [%s] `%s`' % (k, ch, v))
            for x in range(max(0, k - 1), min(len(p_rl), k + 2)):
                mk = '>>' if x == k else '  '
                L.append('  - %s 产物行 %d：%s' % (mk, x, (p_rl[x]['jp'] or '').replace('\n', ' ')[:52]))
        L.append('')
    with open(OUT, 'w', encoding='utf-8', newline='\n') as f:
        f.write('\n'.join(L) + '\n')
    print('CG 序列差异段 %d ; %s' % (len(rep), dict(tot)))
    print('report:', os.path.relpath(OUT, ROOT))


if __name__ == '__main__':
    main()
