# -*- coding: utf-8 -*-
"""解锁位点闸：CG 画廊条目号 / `CG_ACHIEVEMENT` 调用 / `0xF0` 成就调用，不得因还原而丢失。

## 为什么需要这道闸

CG 显示点后面**恒跟一组解锁位点**（本作形状，见 doc/engine-mechanics.md「成就触发点契约」）：

```
0x33 <槽> <资源.PNG> u8 u8
0x0b <u16 A> 01          场景/图库分组
0x0b <u16 B> 01          CG 编号 → 画廊条目
0x04 "CG_ACHIEVEMENT" 00 RunFile 成就脚本（按 var[55] 阈值发收集类成就）
```

这些位点**跟着显示块走、却又不是演出**：`replace` 整槽替换时它们会和显示块一起被删，
`drop_units` 删格时若不保留它们就会连解锁时机一起消失。丢失的症状**完全没有报错**——
玩家侧只能看到「画廊格子永久锁死、收集类成就不弹」。

## 判据（两组，全部落在内容面）

**第一组：不得丢失**

1. **`0x04 CG_ACHIEVEMENT` 逐个 host 数量不减**：Steam 有 N 个，产物必须 ≥ N 个；
2. **`0x0b` 置位值集合不减**：Steam 置过的每个 `A`/`B` 值，产物里仍须存在（值集合差集为空）；
3. **`0xF0` 成就 id 集合不减**：Steam 的每个成就 id 在产物中仍存在。

**第二组：归属不得串号**（`0b (A,B)` 只认 Steam 的编号空间）

4. **产物里每个解锁对 `(A,B)` 都必须属于 Steam 的编号集合**。

   原版与 Steam 是**两套独立编号**（实测同帧 479 个，`B` 系统性错开 1–3 号，仅 10 个巧合相同）。
   原版段的解锁对照抄进产物 ⇒ 数量**变多**、集合**变大**，第一组判据全绿，
   但 `CG_PAGE` 会点亮一张完全不相干的画廊条目。
   **这类缺陷的形态是「值错」，不是「值少」** ⇒ 只查「不减」的闸对它结构性失明。
   不在 Steam 集合内的解锁对，其来源必须能被解释（见 `tool/cgunlock.py` 的处置规则）。
   **限定**：只对「Steam 基线里有同名脚本」的产物脚本判——A-1 整脚本与后日谈 `SL_*`
   在 Steam 侧没有同名脚本，用原版编号是对的。

**为什么用「数量不减 / 集合不减」而不是「逐点位置相等」**：删格会让位点随相邻存活格移位、
还原段会带入原版自己的 `0b` 对（合法增加）。位置比对会把这两种正常形态误判成缺陷，
而**丢失**才是唯一要拦的方向。

## 扫描面

`asset/Rio.arc` 内的 `.ws2` 与 `asset/RIO/*.ws2`（后日谈）两份都扫。线性解析不自洽的脚本
（内含菜单/数据表）跳过并记账，不静默吞掉。

用法：
    python script/checks/cg_unlock_check.py
退出码 1 = 有丢失。
"""
import argparse
import os
import struct
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from tool import arcbuild, cgunlock, ws2, ws2dis  # noqa: E402

CG_ACH = b'CG_ACHIEVEMENT'


def _members_arch(path):
    out = {}
    if not os.path.exists(path):
        return out
    for nb, d in arcbuild.read_raw(path):
        n = nb.decode('utf-16le', 'replace')
        if n.lower().endswith('.ws2'):
            out[n] = d
    return out


def _members_loose(d):
    out = {}
    if not d or not os.path.isdir(d):
        return out
    for fn in sorted(os.listdir(d)):
        if fn.lower().endswith('.ws2'):
            with open(os.path.join(d, fn), 'rb') as f:
                out['RIO/' + fn] = f.read()
    return out


def scan(members):
    """→ (per_script, skipped)。

    `per_script[name] = {'cg': n, 'flags': set(int), 'f0': set(int)}`。
    """
    per, skipped = {}, []
    for name, raw in sorted(members.items()):
        try:
            instrs, ok = ws2dis.disassemble(ws2.decode(raw))
        except Exception as ex:                       # noqa: BLE001 —— 记账，不吞
            skipped.append('%s(%s)' % (name, ex))
            continue
        if not ok:
            skipped.append('%s(linear-parse)' % name)
        cg = 0
        flags, f0 = set(), set()
        for _off, op, _sz, ops in instrs:
            if op == 0x04 and ops.split(b'\x00')[0] == CG_ACH:
                cg += 1
            elif op == 0x0B and len(ops) >= 3:
                flags.add(struct.unpack_from('<H', ops, 0)[0])
            elif op == 0xF0 and ops:
                f0.add(ops[0])
        # 显示点后的解锁对：用于第二组判据（归属不得串号）
        raw_pairs = list(cgunlock.display_unlock_pairs(instrs))
        pairs = {(a, b) for _dn, a, b in raw_pairs}
        per[name] = {'cg': cg, 'flags': flags, 'f0': f0,
                     'pairs': pairs, 'raw_pairs': raw_pairs}
    return per, skipped


def main(argv=None):
    ap = argparse.ArgumentParser(description='解锁位点闸（CG 画廊 / CG_ACHIEVEMENT / 0xF0）')
    ap.add_argument('--product', default=os.path.join(ROOT, 'asset', 'Rio.arc'))
    ap.add_argument('--loose', default=os.path.join(ROOT, 'asset', 'RIO'))
    ap.add_argument('--backup', default=os.path.join(ROOT, 'backup', 'Rio.arc'))
    ap.add_argument('--quiet', action='store_true')
    args = ap.parse_args(argv)

    prod_m = _members_arch(args.product)
    prod_m.update(_members_loose(args.loose))
    base_m = _members_arch(args.backup)
    if not prod_m:
        sys.exit('产物无脚本：%s / %s' % (args.product, args.loose))
    if not base_m:
        sys.exit('基线归档缺失：%s' % args.backup)

    prod, sk_p = scan(prod_m)
    base, sk_b = scan(base_m)

    # 第二组：归属不得串号——产物里每个解锁对都必须属于 Steam 的编号集合
    #
    # ⚠️ **没有「A-1 整脚本无同名脚本 ⇒ 豁免」这一条了**。A-1 的 5 个被删脚本是**整脚本
    # 回填原版内容**，但它们的解锁对落到的是 **Steam 引擎里的 Steam 画廊表**：原版 `(A,B)`
    # 在 Steam 侧没有对应关系（实测同名帧 479 个、B 系统性错开 1–3 号，仅 10 个巧合相同），
    # 照抄会点亮 Steam 画廊里完全不相干的条目——包括指向不存在图的「死条目」，实机表现为
    # 点开或切换差分时报 `ファイルが無かった`。⇒ 判据改成**按帧解析**：与产出端共用
    # `cgunlock.resolve_pair()`，原版独有帧（Steam 无同帧）不得残留解锁对。
    steam_map = {}
    steam_pairs = set()
    for nb, d in arcbuild.read_raw(args.backup):
        n = nb.decode('utf-16le', 'replace')
        if not n.lower().endswith('.ws2'):
            continue
        try:
            instrs, _ok = ws2dis.disassemble(ws2.decode(d))
        except Exception:                         # noqa: BLE001
            continue
        for disp, a, b in cgunlock.display_unlock_pairs(instrs):
            fk = cgunlock.frame_key(disp)
            if fk is not None:
                steam_map.setdefault(fk, (a, b))
            steam_pairs.add((a, b))

    foreign = []
    if steam_map:
        for name, p in sorted(prod.items()):
            # 基线里有同名脚本 ⇒ 其解锁对必须全在 Steam 集合内（值错也是一种缺陷）。
            if name in base:
                bad = (p.get('pairs') or set()) - steam_pairs
                if bad:
                    foreign.append('%s: %d 个解锁对不在 Steam 编号集合 %s'
                                   % (name, len(bad), sorted(bad)[:4]))
            # 新增脚本（A-1 整脚本 / 后日谈 SL_* / RIO 裸文件）⇒ 逐帧校验：
            # 原版独有帧不得残留解锁对，有同帧则必须写成 Steam 的 (A,B)。
            else:
                bad = []
                for disp, a, b in p.get('raw_pairs') or ():
                    want = cgunlock.resolve_pair(disp, steam_map)
                    if want is None:
                        bad.append('%s(无同帧却留了解锁对 %d,%d)' % (disp, a, b))
                    elif (a, b) != want:
                        bad.append('%s(%d,%d≠Steam %d,%d)' % (disp, a, b, want[0], want[1]))
                if bad:
                    foreign.append('%s: %d 处解锁对未落到 Steam 编号空间 %s'
                                   % (name, len(bad), bad[:3]))

    lost = []
    for name, b in sorted(base.items()):
        p = prod.get(name)
        if p is None:
            continue                       # 新增脚本（后日谈/A-1）不在基线，无对照
        if p['cg'] < b['cg']:
            lost.append('%s: CG_ACHIEVEMENT %d -> %d' % (name, b['cg'], p['cg']))
        miss_f = b['flags'] - p['flags']
        if miss_f:
            lost.append('%s: 0b 置位值丢失 %s' % (name, sorted(miss_f)[:8]))
        miss_0 = b['f0'] - p['f0']
        if miss_0:
            lost.append('%s: 0xF0 成就 id 丢失 %s' % (name, sorted(miss_0)))

    ok = not lost and not foreign
    if not args.quiet:
        rep = ['']
        rep.append('解锁位点闸：基线 %d 脚本 / 产物 %d 脚本' % (len(base), len(prod)))
        rep.append('  判据：CG_ACHIEVEMENT 数量不减 ∧ 0b 置位值集合不减 ∧ 0xF0 成就 id 集合不减')
        if lost:
            rep.append('  ✗ 丢失：')
            for x in lost[:30]:
                rep.append('    ' + x)
            if len(lost) > 30:
                rep.append('    …共 %d 条' % len(lost))
        if foreign:
            rep.append('  ✗ 归属串号（解锁对不属于 Steam 编号集合）：')
            for x in foreign[:30]:
                rep.append('    ' + x)
            if len(foreign) > 30:
                rep.append('    …共 %d 条' % len(foreign))
        if not lost and not foreign:
            rep.append('  ✓ 全部脚本通过（无丢失 / 无串号）')
        sk = sorted(set(sk_b) | set(sk_p))
        if sk:
            rep.append('  线性解析不自洽（跳过，非静默）：%d 个 %s' % (len(sk), sk[:6]))
        rep.append('  => %s' % ('PASS' if ok else 'FAIL'))
        print('\n'.join(rep))
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
