# -*- coding: utf-8 -*-
"""子图层闸：产物每条立绘显示指令引用的**子图**是否与原版一致。

判据（与判定表生成器共用 `tool/perfsync.py` + `tool/subimg.py`）
--------------------------------------------------------------
脚本用 `0x39`（建层）指令列出**子图层 id**，引擎就按这些 id 从当前加载的 `.pna` 里取子图。
逐位比「当前 PNA 在该 id 的子图」与「原版对应子图」：

- **字节级相同**或**像素相同**（仅重编码噪声）⇒ 这一位合格；
- 否则 ⇒ 该槽必须已由演出同步表/人工表处置成「整段换成原版行」（`replace`：带回原版图名 ＋
  原版 id 列表）——处置后再比就应当全是「字节级相同」。

为什么不能只看图名：Steam 把立绘的**差分（表情）层重新编排**过（同一姿势的 id 列表不同、
PNA 里部分差分槽位成了重复图），只看归一后的图名会静默放过（实机症状：立绘表情与场景不符）。

输出：`tmp/subimage_check.md` + 退出码（有未处置的不一致 ⇒ 1）。
"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
from tool import arcbuild, perfsync, subimg, ws2, ws2dis, ws2conv  # noqa: E402

OUT = os.path.join(ROOT, 'tmp', 'subimage_check.md')


def load_rio(path):
    return {k.decode('utf-16le', 'replace'): d for k, d in arcbuild.read_raw(path)}


def main():
    orig_dir = os.environ.get('IFMH_ORIG_DIR', '')
    if not orig_dir or not os.path.isdir(orig_dir):
        print('需要原版目录：IFMH_ORIG_DIR')
        return 2
    plan = json.load(open(os.path.join(ROOT, 'resource', 'restore_plan.json'), encoding='utf-8'))
    carrier = json.load(open(os.path.join(ROOT, 'resource', 'carrier_map.json'), encoding='utf-8'))
    prod_rio, orig_rio = load_rio(os.path.join(ROOT, 'asset', 'Rio.arc')), load_rio(
        os.path.join(orig_dir, 'Rio.arc'))
    # 对齐表必须按 **Steam 基线**行建（与判定表生成器同源）：产物行序被 drops 压缩、
    # inserts 平移，拿它建键再用 Steam 槽号去查会系统性错位（实测会造出 1,639 处假「不可信」）。
    base_rio = load_rio(os.path.join(ROOT, 'backup', 'Rio.arc'))
    cur_pna = subimg.index_pna(os.path.join(ROOT, 'asset'))          # 产物侧（已含补入的原版成员）
    org_pna = subimg.index_pna(orig_dir)
    tab = {}

    def table(blob):
        key = id(blob)
        if key not in tab:
            tab[key] = subimg.subimage_table(blob)
        return tab[key]

    bad, ok, noalign, nolid, flat, repoint, untrusted, unknown = [], 0, 0, 0, 0, [], 0, []
    for script, pl in sorted(plan['hosts'].items()):
        if pl.get('kind') == 'skip' or script + '.ws2' not in prod_rio:
            continue
        try:
            s_instrs = ws2dis.disassemble(ws2.decode(prod_rio[script + '.ws2']))[0]
            o_instrs = ws2dis.disassemble(ws2.decode(
                ws2conv.convert_script(orig_rio[script + '.ws2'], orig_dir)))[0]
            srows = perfsync.row_instrs(s_instrs)
            orows = perfsync.row_instrs(o_instrs)
            s_own = [r['own'] for r in perfsync.perf_rows(s_instrs)]
            o_own = [r['own'] for r in perfsync.perf_rows(o_instrs)]
            # 与生成器同源：对齐表用 **Steam 基线**行的 own
            b_instrs = ws2dis.disassemble(ws2.decode(base_rio[script + '.ws2']))[0]
            b_own = [r['own'] for r in perfsync.perf_rows(b_instrs)]
        except Exception:
            continue
        # 与生成器（build_perf_sync_map.py）**同一条对齐链**：承载图 anchor/match 内插
        # ＋语音号自证补 ambiguous 缺口。口径不一致会让闸报出生成器根本没看到的槽。
        s2o = perfsync.interp_align(perfsync.voice_align(
            b_own, o_own, perfsync.align_map(script, carrier), override=True))
        srcs = (pl.get('plan') or {}).get('slot_sources') or []
        for k, rows in enumerate(srows):
            blk = [b for b in perfsync.image_blocks(rows)
                   if b['kind'] == 'display' and (b['chan'] or '').startswith('st')]
            if not blk:
                continue
            name = blk[0]['name']
            if not (name or '').lower().endswith('.pna'):
                flat += 1                       # 普通 PNG：无子图概念，不在本闸范围
                continue
            ids_cur = perfsync.layer_ids(rows, blk[0]['chan'])
            src = srcs[k] if k < len(srcs) else ['?', -1]
            o = src[1] if src[0] == 'orig' else s2o.get(src[1])
            if o is None or o >= len(orows):
                noalign += 1
                continue
            # 与生成器同一条**可信闸**：两侧本槽自带语音号必须相等（含两侧皆无），否则
            # 判承载图假配对（假锚会把别的行的演出搬过来，见 doc/restoration-route.md §6 V-10）⇒ 不处置。
            pv = s_own[k].get('voice') if k < len(s_own) else None
            ov = o_own[o].get('voice') if o < len(o_own) else None
            if not ((pv == ov) or ((script, k) in perfsync.align_fixes())):
                untrusted += 1
                continue
            oblk = [b for b in perfsync.image_blocks(orows[o])
                    if b['kind'] == 'display' and (b['chan'] or '').startswith('st')]
            if not oblk:
                ok += 1
                continue
            ids_org = perfsync.layer_ids(orows[o], oblk[0]['chan'])
            if not ids_cur or not ids_org:
                nolid += 1
                continue
            org_name = perfsync.norm_sprite((oblk[0]['name'] or '').upper())
            v = perfsync.subimage_verdict(table(subimg.resolve(cur_pna, org_pna, name)),
                                          table(org_pna.get(org_name.lower())),
                                          ids_cur, ids_org)
            if v == 'same':
                ok += 1
            elif v == 'repoint':
                repoint.append((script, k, o, name, org_name, ids_cur, ids_org))
            elif v == 'unknown':
                unknown.append((script, k, name, ids_cur, ids_org))
            else:
                bad.append((script, k, src[1] if src[0] == 'steam' else o, name, org_name,
                            ids_cur, ids_org, v))
    lines = ['# 子图层闸（产物立绘引用的子图 vs 原版）', '',
             '- 合格（字节级相同或仅重编码噪声）：**%d**' % ok,
             '- 需引入原版（当前 PNA 内找不到原版那张；同名 ⇒ 整名覆盖）：**%d**' % len(bad),
             '- 只须改脚本 id（当前 PNA 内另有相同子图）：**%d**' % len(repoint),
             '- 无对齐来源：%d ；语音自证不通过（假锚风险，不处置）：%d ；id 语义不适用：%d ；脚本未列建层表：%d ；普通 PNG：%d'
             % (noalign, untrusted, len(unknown), nolid, flat),
             '']
    for b in bad[:200]:
        lines.append('- [引入] %s p%d (对齐 o%s) 图名 %s → 原版 %s  id %s ↔ %s'
                     % (b[0], b[1], b[2], b[3], b[4], b[5], b[6]))
    for r in repoint[:50]:
        lines.append('- [改 id] %s p%d (对齐 o%d) 图名 %s id %s ↔ %s'
                     % (r[0], r[1], r[2], r[3], r[5], r[6]))
    for u in unknown[:20]:
        lines.append('- [不适用] %s p%d 图名 %s id %s ↔ %s'
                     % (u[0], u[1], u[2], u[3], u[4]))
    open(OUT, 'w', encoding='utf-8').write('\n'.join(lines) + '\n')
    print('子图层闸：合格 %d ；需引入 %d ；只需改 id %d ；无对齐 %d ；不可信 %d ；id语义不适用 %d ；无建层表 %d ；普通 PNG %d'
          % (ok, len(bad), len(repoint), noalign, untrusted, len(unknown), nolid, flat))
    print('report: %s' % OUT)
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main())
