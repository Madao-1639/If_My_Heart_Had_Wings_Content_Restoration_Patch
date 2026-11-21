# -*- coding: utf-8 -*-
"""跨引擎标志词表闸：产物里 `0x46`/`0x47` 的取值必须落在 **Steam 引擎自身词表**内。

## 为什么这是一道闸而不是注释

`0x46`（子层槽绑定）与 `0x47`（Effect1 参数来源）的词表在两侧**零交叉**：

| 指令 | 字段 | 原版取值 | Steam 取值 | 带原版取值进 Steam 引擎的后果 |
|---|---|---|---|---|
| `0x46` | 标志字节 | `0x00` / `0x80` | `0x00` / `0xf0` | 子层槽**欠绑定** ⇒ 未重绑的槽保留上一次显示的子图（立绘残留 / 表情层错位） |
| `0x47` | `B`（bit7＝参数走变量表） | `0x00` / `0x80` | `0x00` / `0x10` / `0xc0` | 参数来源位失配 ⇒ 动画照跑、**终点不对**（不报错、不闪退） |

两者都是**静默**的：引擎对越界处置是「记错误并跳过整条」而非崩溃，所以机检不查就永远
不会有人发现（语义与依据见 doc/engine-mechanics.md「动画组的工作机制」）。

## 判据

* 产物所有 `0x46` 的标志 ∈ `{0x00, 0xf0}`；
* 产物所有 `0x47` 的 `B` ∈ `{0x00, 0x10, 0xc0}`；
* 原版取值（`0x80`）的计数必须为 **0**（这才是「内容面」判据——只看集合不看计数时，
  只要两种取值里有一种合法就会被判通过）。

## 扫描面

两份都要扫（少扫一处就会留静默缺口）：

* `asset/Rio.arc` 等归档内的 `.ws2` 成员（本体与后日谈合并的脚本）；
* `asset/RIO/*.ws2` 裸脚本（后日谈 `SL_*` 走裸文件，不在任何归档里——实测这四份在本轮
  归一之前共有 **850 处** `0x80` 越界（`0x46` 810 / `0x47` 40），当时没有任何闸能看见）。

线性解析不自洽的脚本（内含菜单/数据表，`ws2dis` 明示不适用）跳过并记账，不静默吞掉。

用法：
    python script/checks/op46_flag_check.py [--product asset] [--loose asset/RIO]
退出码 1 = 有越界取值。
"""
import argparse
import collections
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from tool import arcbuild, ws2, ws2dis  # noqa: E402

OK_46 = {0x00, 0xf0}
OK_47 = {0x00, 0x10, 0xc0}
ORIG_VALUE = 0x80           # 原版工具链唯一多出来的取值


def _flag46(ops):
    """`<通道>\\0` ＋ u16 ＋ u8 标志 ＋ 4×f32 ⇒ 标志在首个 NUL 之后第 3 字节。"""
    i = ops.find(b'\x00')
    return ops[i + 3] if (0 <= i and len(ops) > i + 3) else None


def _flag47(ops):
    """`<通道>\\0<特效>\\0` ＋ u16 sel ＋ u8 A ＋ u8 B ⇒ B 在第二个 NUL 之后第 5 字节。"""
    i = ops.find(b'\x00')
    j = ops.find(b'\x00', i + 1) if i >= 0 else -1
    return ops[j + 4] if (j >= 0 and len(ops) > j + 4) else None


def scan(members, tag):
    """扫一份脚本集合 → (计数, 越界明细, 跳过明细)。"""
    cnt46, cnt47 = collections.Counter(), collections.Counter()
    bad, skipped = [], []
    for name, raw in sorted(members.items()):
        if not name.lower().endswith('.ws2'):
            continue
        # `0x04 LAYER_ORDER` 之类的变长块让个别脚本线性解析不自洽：跳过并记账
        try:
            instrs, ok = ws2dis.disassemble(ws2.decode(raw))
        except Exception as ex:                       # noqa: BLE001 —— 记录而不吞
            skipped.append('%s(%s)' % (name, ex))
            continue
        if not ok:
            skipped.append('%s(linear-parse)' % name)
        for off, op, size, ops in instrs:
            if op == 0x46:
                v = _flag46(ops)
                if v is None:
                    continue
                cnt46[v] += 1
                if v not in OK_46:
                    bad.append({'script': name, 'op': '0x46', 'off': off, 'flag': v})
            elif op == 0x47:
                v = _flag47(ops)
                if v is None:
                    continue
                cnt47[v] += 1
                if v not in OK_47:
                    bad.append({'script': name, 'op': '0x47', 'off': off, 'flag': v})
    return {'tag': tag, 'c46': cnt46, 'c47': cnt47, 'bad': bad, 'skipped': skipped}


def collect(product, loose):
    """收集待扫脚本 → `{显示名: 原始字节}`。

    `product`：归档文件（如 `asset/Rio.arc`）；`loose`：裸脚本目录（如 `asset/RIO`）。
    后日谈 `SL_*.ws2` 走裸文件，不在任何归档里，漏扫就会漏整条交付链。
    """
    out = {}
    if product and os.path.exists(product):
        for nb, d in arcbuild.read_raw(product):
            n = nb.decode('utf-16le', 'replace')
            if n.lower().endswith('.ws2'):
                out[n] = d
    if loose and os.path.isdir(loose):
        for fn in sorted(os.listdir(loose)):
            if not fn.lower().endswith('.ws2'):
                continue
            with open(os.path.join(loose, fn), 'rb') as f:
                out['RIO/' + fn] = f.read()
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description='跨引擎标志词表闸（0x46 / 0x47）')
    ap.add_argument('--product', default=os.path.join(ROOT, 'asset', 'Rio.arc'))
    ap.add_argument('--loose', default=os.path.join(ROOT, 'asset', 'RIO'),
                    help='裸脚本目录（后日谈 SL_*.ws2）；传空串跳过')
    ap.add_argument('--quiet', action='store_true')
    args = ap.parse_args(argv)

    if not os.path.exists(args.product):
        sys.exit('产物归档不存在：%s' % args.product)
    members = collect(args.product, args.loose)
    if not members:
        sys.exit('没有可扫的脚本：%s / %s' % (args.product, args.loose))
    r = scan(members, 'product')

    bad_orig = sum(1 for x in r['bad'] if x['flag'] == ORIG_VALUE)
    other = len(r['bad']) - bad_orig
    ok = not r['bad']

    if not args.quiet:
        rep = ['']
        rep.append('标志词表闸：%s ＋ %s（%d 个脚本）'
                   % (os.path.relpath(args.product, ROOT),
                      os.path.relpath(args.loose, ROOT) if args.loose else '—',
                      len(members)))
        rep.append('  0x46 标志分布 = %s（合法 %s）'
                   % (dict(sorted(r['c46'].items())), sorted(OK_46)))
        rep.append('  0x47 B 分布  = %s（合法 %s）'
                   % (dict(sorted(r['c47'].items())), sorted(OK_47)))
        rep.append('  越界取值：原版词表值(0x80) %d 处；其它越界 %d 处'
                   % (bad_orig, other))
        for x in r['bad'][:20]:
            rep.append('    %s %s @%#x = %#04x'
                       % (x['script'], x['op'], x['off'], x['flag']))
        if len(r['bad']) > 20:
            rep.append('    …共 %d 处' % len(r['bad']))
        if r['skipped']:
            rep.append('  线性解析不自洽（跳过，非静默）：%d 个 %s'
                       % (len(r['skipped']), r['skipped'][:6]))
        rep.append('  => %s' % ('PASS' if ok else 'FAIL'))
        print('\n'.join(rep))
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
