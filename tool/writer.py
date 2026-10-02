# -*- coding: utf-8 -*-
"""宿主脚本结构写盘器（本体线）。

把判读台账的处置落到 Steam 宿主脚本字节上：

- **删格**：整格删除（`14` + 邻接 `15`，带「不改动任何存活格名字框」守卫，移植 CC 算法）。
- **插入原版块**：台账行区间 → 原版指令 span（行 = 原 `14`，已实证 1:1）→ 逐条过
  `tool.ws2conv.CONV` 格式差 → 块内跳转立即重定基；跨块目标由计划器的
  `external` 表（orig off → steam 槽位）解析到宿主 `14` 的新偏移。
- **池序号全量重算**：`14.id` 与 `0f` 各条目 strid 同一「文件出现序」编号空间。
- **跳转回写**：`01.a/b`、`02`、`06`、`0f` 体内 `06` —— 单遍发出 + 末端按完整
  偏移映射统一回写（前向/后向目标都覆盖）。
- **恢复现场**：插入块之后，若紧随的 Steam 指令不是 `15`，重发进入时的名字框
  （靠继承取名的存活格会张冠李戴，移植 CC 教训）。

产出 `slot_sources`：最终槽位序 → `('steam', old_idx)` / `('orig', row)`，
供 zh-CN 覆盖层按槽现做 `.lng`（保留格直取官方条目、插入格取民汉）。

A-1 整脚本不走本模块（整脚本走 `tool.ws2conv.convert_script`，槽位与
`resource/fan_cn` 1:1）。0f 不得出现在插入块内（实证：全部 orig 源零 0f）。
"""
import struct

from tool import ws2, ws2dis
from tool.ws2conv import CONV, REBASE_OPS, parse as conv_parse

BLOCK_STOP = {0x01, 0x02, 0x06, 0x07, 0xFF}   # 原版块在其前截断（其后属宿主结尾）


def _pfx(ops):
    """`15` 操作数 → 名字框前缀字节（布局 = prefix_cstr + 1 字节 0x00）。"""
    return ops[:-2]


def _mk15(prefix):
    return b'\x15' + prefix + b'\x00\x00'


def eff_names(instrs, skip=frozenset()):
    """每个 `14` 槽位的生效名字框（其上最近一条未跳过 `15` 的前缀；0f 条目继承）。"""
    out, cur = [], None
    for off, op, size, ops in instrs:
        if off in skip:
            continue
        if op == 0x15:
            cur = _pfx(ops)
        elif op == 0x14:
            out.append(cur)
        elif op == 0x0F:
            out.extend([cur] * ops[1])
    return out


def drop_units(instrs, drop_slots):
    """删格偏移集：被删槽的 `14` + 邻接 `15`（守卫：试删后任何存活格生效名字框不得改变）。"""
    slot_of = {}
    k = 0
    for off, op, size, ops in instrs:
        if op == 0x14:
            slot_of[off] = k
            k += 1
    kill = {off for off, op, size, ops in instrs
            if op == 0x14 and slot_of.get(off) in drop_slots}
    idx = {ins[0]: j for j, ins in enumerate(instrs)}
    cand = set()
    for o in kill:
        j = idx[o]
        for d in (j - 1, j + 1):
            if 0 <= d < len(instrs) and instrs[d][1] == 0x15:
                cand.add(instrs[d][0])
    if not cand:
        return kill
    base = eff_names(instrs, kill)
    keep = {o for o in cand if eff_names(instrs, kill | {o}) != base}
    return kill | (cand - keep)


def _conv(op, ops, names=None):
    rule = CONV.get(op)
    if rule is None:
        ops2 = ops
    else:
        kind, tail = rule
        if kind == 'mid1':
            assert len(ops) >= tail
            ops2 = ops[:-tail] + b'\x00' + ops[-tail:]
        elif kind == 'end1':
            ops2 = ops + b'\x00'
        else:
            ops2 = ops + b'\x00\x00\x00\x00'
    if names:
        ops2 = apply_names(ops2, names)
    return ops2


def apply_names(dec, names):
    """在解码流内做等长资源名替换（NUL 定界精确匹配；长度必须一致）。

    names = {旧名bytes(任意大小写): 新名bytes}——改名资源的脚本引用同步。
    """
    for old, new in names.items():
        assert len(old) == len(new), '改名长度不一致: %r -> %r' % (old, new)
        dec = dec.replace(b'\x00' + old + b'\x00', b'\x00' + new + b'\x00')
        dec = dec.replace(b'\x00' + old.upper() + b'\x00', b'\x00' + new + b'\x00')
        dec = dec.replace(b'\x00' + old.lower() + b'\x00', b'\x00' + new + b'\x00')
    return dec


def rebuild_host(steam_dec, orig_dec, plan, orig_fmts):
    """重建宿主脚本。

    plan = {
      'drops':   [steam 槽位(14 序)]                       # 整格删除
      'inserts': [(after_slot, r0, r1)],                  # 原版行闭区间；after_slot=-1 脚本头
      'external': {orig_off: steam_slot},                 # 跨块跳转解析（缺省空）
      'restore_frame': True,                              # 插入后恢复名字框（缺省开）
    }
    返回 {'raw', 'slot_sources', 'ok', 'n14', 'n_slots', 'pool', 'fixups', 'fix_bad'}。
    """
    ext = plan.get('external', {})
    restore_frame = plan.get('restore_frame', True)
    names = {k.encode('ascii'): v.encode('ascii') for k, v in plan.get('names', {}).items()}

    sinstrs, ok = ws2dis.disassemble(steam_dec)
    assert ok, 'host steam-table parse not self-consistent: %s' % plan.get('script', '?')
    oinstrs, otail = conv_parse(orig_dec, orig_fmts)
    ooff, p = [], 0
    for op, ops in oinstrs:
        ooff.append(p)
        p += 1 + len(ops)
    o14 = [j for j, (op, ops) in enumerate(oinstrs) if op == 0x14]   # 行 r ↔ o14[r]

    kill = drop_units(sinstrs, set(plan['drops']))
    s14off = [off for off, op, size, ops in sinstrs if op == 0x14]

    # 宿主结尾起点：最后一个保留 14 之后的第一条流程控制指令
    kept_slots = [s for s in range(len(s14off)) if s not in plan['drops']]
    tail_end_off = None
    if kept_slots:
        koff = s14off[kept_slots[-1]]
        for off2, op2, size2, ops2 in sinstrs:
            if off2 > koff and op2 in (0x01, 0x02, 0x06, 0x07, 0xFF):
                tail_end_off = off2
                break
    by_anchor = {}
    for a, r0, r1 in plan['inserts']:
        assert a == -1 or 0 <= a < len(s14off), '插入锚非法: %r' % (a,)
        assert a == -1 or a not in plan['drops'], '插入锚落在被删格: %d' % a
        by_anchor.setdefault(a, []).append((r0, r1))
    for a, ranges in by_anchor.items():
        if a >= 0:
            ranges.sort()
            assert all(r1 < r2 for (_, r1), (r2, _) in zip(ranges, ranges[1:])), \
                '锚 %d 的插入区间须按原版行序排列' % a

    def block_span(r0, r1):
        i0 = o14[r0 - 1] + 1 if r0 > 0 else 0
        if r1 + 1 < len(o14):
            i1 = o14[r1 + 1]
        else:
            i1 = len(oinstrs)
            for j in range(o14[r1] + 1, len(oinstrs)):
                if oinstrs[j][0] in BLOCK_STOP:
                    i1 = j
                    break
        n14 = sum(1 for j in range(i0, i1) if oinstrs[j][0] == 0x14)
        assert n14 == r1 - r0 + 1, '块 14 数 %d != 行数 %d（r%d-%d）' % (n14, r1 - r0 + 1, r0, r1)
        assert not any(oinstrs[j][0] == 0x0F for j in range(i0, i1)), \
            '块内含 0f（还原内容不得携带选项，r%d-%d）' % (r0, r1)
        return i0, i1

    out = bytearray()
    remap_s, remap_o = {}, {}
    slot_sources = []
    fixes = []                      # (out 内绝对写位, 's'|'o'|'x', key)
    pool = 0
    si = 0                          # 14 序（= 台账槽位口径）
    buf15 = None
    buf15_off = None
    cur_pfx = b''

    def flush15():
        nonlocal buf15, buf15_off
        if buf15 is not None:
            remap_s[buf15_off] = len(out)
            out.extend(buf15)
            buf15 = None
            buf15_off = None

    def emit_block(r0, r1, after_off):
        nonlocal pool
        i0, i1 = block_span(r0, r1)
        base = len(out)
        rel = {}
        q = 0
        for j in range(i0, i1):
            op, ops = oinstrs[j]
            rel[ooff[j]] = q
            q += 1 + len(_conv(op, ops))
        for j in range(i0, i1):
            op, ops = oinstrs[j]
            ops2 = _conv(op, ops, names)
            for k in REBASE_OPS.get(op, ()):
                v = struct.unpack_from('<I', ops2, k)[0] if len(ops2) >= k + 4 else 0
                if not v:
                    continue
                if v in rel:                                    # 块内：立即重定基
                    ops2 = ops2[:k] + struct.pack('<I', base + rel[v]) + ops2[k + 4:]
                elif ext.get(v) == 'tail_end':                  # 原版结尾 ⇒ 宿主结尾
                    fixes.append((len(out) + 1 + k, 't', v))
                elif v in ext:                                  # 跨块：末端经宿主映射
                    fixes.append((len(out) + 1 + k, 'x', v))
                else:
                    raise AssertionError('跨块跳转目标 %#x（op %#x @%#x）无承载'
                                         % (v, op, ooff[j]))
            out.extend(bytes([op]) + ops2)
            remap_o[ooff[j]] = base + (len(out) - base - (1 + len(ops2)))
            if op == 0x14:
                row = o14.index(j)
                slot_sources.append(('orig', row))
                pool += 1
        if restore_frame:
            nxt = next((ins for ins in sinstrs if ins[0] > after_off), None)
            if nxt is not None and nxt[1] != 0x15:
                out.extend(_mk15(cur_pfx))

    # 脚本头插入
    for r0, r1 in by_anchor.get(-1, []):
        emit_block(r0, r1, -1)

    pos = 0
    for off, op, size, ops in sinstrs:
        pos = off + size
        if off in kill:
            if op == 0x14:
                si += 1
            continue
        if op == 0x15:
            if buf15 is not None:
                remap_s[buf15_off] = len(out)
                out.extend(buf15)
            buf15 = steam_dec[off:off + size]
            buf15_off = off
            cur_pfx = _pfx(ops)
            continue
        flush15()
        remap_s[off] = len(out)
        body = bytearray(steam_dec[off:off + size])   # 全指令（含操作码）
        if op == 0x14:
            old = struct.unpack_from('<H', body, 1)[0]
            struct.pack_into('<H', body, 1, pool)
            slot_sources.append(('steam', old))
            pool += 1
        elif op == 0x0F:
            n = body[1]
            pp = 3                                    # body[0]=0f, [1]=count, 条目自 3 起
            for _ in range(n):
                old_strid = struct.unpack_from('<H', body, pp)[0]
                struct.pack_into('<H', body, pp, pool)
                slot_sources.append(('steam', old_strid))
                pool += 1
                e1 = body.index(b'\x00', pp + 2) + 1
                jmp = body[e1 + 3]
                if jmp == 0x06:
                    tgt = struct.unpack_from('<I', body, e1 + 4)[0]
                    if tgt:
                        fixes.append((len(out) + e1 + 4, 's', tgt))
                pp = (body.index(b'\x00', e1 + 4) + 1) if jmp == 0x07 else (e1 + 3 + 5)
            body = bytes(body)
        elif op in (0x01, 0x02, 0x06):
            for k in REBASE_OPS.get(op, ()):
                v = struct.unpack_from('<I', ops, k)[0] if len(ops) >= k + 4 else 0
                if v:
                    fixes.append((len(out) + 1 + k, 's', v))
        out.extend(body)
        if op == 0x14:
            si += 1
            for r0, r1 in by_anchor.get(si - 1, []):
                emit_block(r0, r1, off)
    flush15()
    out.extend(steam_dec[pos:])                       # 0xff 后的 8 字节尾

    fix_bad = 0
    for pos, kind, key in fixes:
        if kind == 's':
            nt = remap_s.get(key)
        elif kind == 'o':
            nt = remap_o.get(key)
        elif kind == 't':
            nt = remap_s.get(tail_end_off)
        else:
            slot = ext[key]
            nt = remap_s.get(s14off[slot]) if slot < len(s14off) else None
        if nt is None:
            fix_bad += 1
            continue
        struct.pack_into('<I', out, pos, nt)

    enc = ws2.encode(bytes(out))
    ins2, ok2 = ws2dis.disassemble(ws2.decode(enc))
    n14 = sum(1 for _, op, _, _ in ins2 if op == 0x14)
    return {
        'raw': enc,
        'slot_sources': slot_sources,
        'ok': ok2,
        'n14': n14,
        'n_slots': len(slot_sources),
        'pool': pool,
        'fixups': len(fixes),
        'fix_bad': fix_bad,
    }
