# -*- coding: utf-8 -*-
"""WS2 尾表闸：产物脚本末尾 8 字节明文表 == 实算的 (消息数, 选项条目数)。

为什么这是硬闸
--------------
引擎**加载脚本时**读文件**末尾 8 字节**（`data[size-8]` / `data[size-4]`），用来给
「已读消息位图」（存档目录 `MessageFlag.dat`）分配 `(消息数+选项条目数+7)/8` 字节；
写位函数 `bitmap[idx>>3] |= 1<<(idx&7)` **不做边界检查** ⇒ 尾表小于脚本真实消息数时，
高位下标直接写到相邻堆块上，延迟到某次 `free` 被堆校验抓到 ⇒ `0xc0000374` **概率性闪退**
（不是崩在写位处）。实机指纹：`MessageFlag.dat` 记录位图容量明显小于脚本消息数、
且该记录 `B`（已标记次数）持续增大而位图仍为 0。

⇒ 任何改变 `0x14` / `0x0f` 条数的改写（插入、删格、拆格、换脚本）都必须**同步重写**这 8 字节，
   写成**明文**、且在 `encode()` **之后**（先写会被旋转成垃圾）。
   本仓库的落地点在 `tool/writer.py::rebuild_host`（插入/删格唯一入口）。

判据
----
- 产物每个 `.ws2` 成员：`read_tail_counts(raw) == ws2.tail_counts(decode(raw))`。
- 与基线（`backup/` 同名归档）逐成员比：基线**自己就偏离**的脚本（本作 Steam 基线有 3 个：
  `CG_PAGE09`、`CG_PAGE11`、`CO1_020`）不计入「新增破坏」——它们的问题不是补丁造成的，
  但也一并打印，便于决定是否顺手修。
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
from tool import arcbuild, ws2  # noqa: E402

ASSET = os.path.join(ROOT, 'asset')
BACKUP = os.path.join(ROOT, 'backup')


def members(path):
    return {nb.decode('utf-16le', 'replace'): d for nb, d in arcbuild.read_raw(path)}


def main():
    arcs = []
    for dirpath, _dirs, files in os.walk(ASSET):
        for fn in files:
            if fn.lower().endswith('.arc'):
                arcs.append(os.path.relpath(os.path.join(dirpath, fn), ASSET).replace('\\', '/'))
    n_ok = n_new = n_inherit = 0
    for rel in sorted(arcs):
        ap = os.path.join(ASSET, rel)
        try:
            ms = members(ap)
        except Exception as ex:
            print('  SKIP %-22s (%s)' % (rel, ex))
            continue
        if not any(n.lower().endswith('.ws2') for n in ms):
            continue
        bp = os.path.join(BACKUP, rel)
        base = members(bp) if os.path.exists(bp) else None
        ok, bad = ws2.check_tails(ms, base)
        danger = [(n, c, t) for n, c, t in bad if t[0] < c[0]]
        n_ok += len(ok)
        n_new += len(danger)
        inherit = []
        if base:
            for name, raw in ms.items():
                if not name.lower().endswith('.ws2') or name not in base:
                    continue
                b_cnt = ws2.tail_counts(ws2.decode(base[name]))
                if b_cnt != ws2.read_tail_counts(base[name]):
                    inherit.append((name, b_cnt, ws2.read_tail_counts(base[name])))
        n_inherit += len(inherit)
        print('  %-22s 成员 %d，尾表正确 %d，**危险 %d**（尾表<消息数），其余偏离 %d，基线自带 %d'
              % (rel, len(ms), len(ok), len(danger), len(bad) - len(danger), len(inherit)))
        for name, cnt, tail in danger:
            print('      危险 %-18s 实算消息=%d 尾表消息=%d（容量缺 %d 位）'
                  % (name, cnt[0], tail[0], cnt[0] - tail[0]))
        for name, cnt, tail in bad:
            if tail[0] >= cnt[0]:
                print('      偏离 %-18s 实算=%s 尾表=%s（冗余，不致命）' % (name, cnt, tail))
        for name, cnt, tail in inherit:
            print('      基线 %-18s 实算=%s 尾表=%s（非本补丁造成）' % (name, cnt, tail))
    print()
    if n_new:
        print('ws2_tail_check: FAIL 危险 %d 个（尾表 < 真实消息数 ⇒ 引擎写位图越界 ⇒ 概率性闪退）'
              % n_new)
        return 1
    print('ws2_tail_check: PASS（尾表正确 %d 个；基线自带偏离 %d 个）' % (n_ok, n_inherit))
    return 0


if __name__ == '__main__':
    sys.exit(main())
