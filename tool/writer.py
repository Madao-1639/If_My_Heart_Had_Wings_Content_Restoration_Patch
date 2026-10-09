# -*- coding: utf-8 -*-
"""宿主脚本结构写盘器（本体线）。

把判读台账的处置落到 Steam 宿主脚本字节上：

- **删格**：删被删行的正文指令 `14` ＋**该行的演出前缀区**（上一条 `14` 之后 → 本行 `14`
  之前）内除 `KEEP_OPS` 外的全部指令（语音/显示/BGM/图层/特效——纯表现，删之无副作用）
  ＋它自带的名字框指令 `15`（带「不改动任何存活格名字框」守卫，移植 CC 算法）。
  **状态写入（`09`/`0b`）、跳转（`01`/`02`/`06`/`07`）、菜单（`0f`）、成就（`f0` 与
  非 `LAYER_ORDER` 的 `04` 调用）一律逐字节保留**——删演出残留的原因见
  `doc/lessons-learned.md` §16（残留排在插入的原版块之后执行 ⇒ 把画面/BGM 顶回
  Steam 素材、并造成无对白连播语音）。
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

# 被删行「演出前缀区」内**保留**的操作码：状态写入（`09` 变量/图层权重、`0b` 布尔）、
# 流程控制（`01`/`02`/`06`/`07`）、菜单（`0f`）、成就（`f0`）、名字框（`15`）、终结符。
# 其余（语音 `2e`+`28`、显示 `33`/`34`、BGM `1e`、图层定位 `46`、特效…）都是**纯表现**，
# 随该行一起删——否则它们排在插入的原版块之后执行，会把画面/BGM 顶回 Steam 素材，
# 并造成「相邻两条语音触发之间没有 14」的无对白连播（见 doc/lessons-learned.md §16）。
KEEP_OPS = {0x01, 0x02, 0x05, 0x06, 0x07, 0x09, 0x0B, 0x0F, 0x15, 0xF0, 0xFF}


def _keep_in_perf_zone(op, ops):
    """演出前缀区内的指令是否保留（保留 = 状态/流程/成就；`04` 只保留非 LAYER_ORDER 调用）。"""
    if op in KEEP_OPS:
        return True
    if op == 0x04:
        return ops.split(b'\x00')[0] != b'LAYER_ORDER'
    return False


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
    """删格偏移集。

    三项内容：
      1. 被删槽的正文指令 `14`；
      2. 该槽**演出前缀区**（上一条 `14` 之后 → 本槽 `14` 之前）内**除 KEEP_OPS 外**的
         全部指令——即该行自己的语音/显示/BGM/图层/特效，删之无状态与流程副作用；
      3. 邻接 `15`（守卫：试删后任何存活格生效名字框不得改变）。
    """
    slot_of = {}
    k = 0
    for off, op, size, ops in instrs:
        if op == 0x14:
            slot_of[off] = k
            k += 1
    kill = {off for off, op, size, ops in instrs
            if op == 0x14 and slot_of.get(off) in drop_slots}
    # 演出前缀区：从被删 `14` 往前扫到上一条 `14`（不含），删掉其中的非 KEEP_OPS 指令
    idx = {ins[0]: j for j, ins in enumerate(instrs)}
    for o in sorted(kill):
        i = idx[o] - 1
        while i >= 0 and instrs[i][1] != 0x14:
            if not _keep_in_perf_zone(instrs[i][1], instrs[i][3]):
                kill.add(instrs[i][0])
            i -= 1
    # 邻接 15（守卫：试删后任何存活格生效名字框不得改变）
    cand = set()
    for o in sorted(kill):
        j = idx[o]
        if instrs[j][1] != 0x14:
            continue
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
      'drops':   [steam 槽位(14 序)]                       # 删该行的文本与名字框指令
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
    ins_rows = set()
    for _a, r0, r1 in plan['inserts']:
        ins_rows.update(range(r0, r1 + 1))
    del ins_rows   # 保留计算仅为可读性；块跨度已不再依赖它（见 block_span 注释）

    def block_span(r0, r1):
        """块 = 行 r0..r1 各自的**演出前缀 ＋ 正文**。

        右端收到 r1 的 `14` **之后**即止（`o14[r1]+1`），**不再携带 r1+1 的演出前缀**：
        那一段在宿主侧由对应槽自带、或由承载 r1+1 的那一块自带，本块再带一遍就会让
        同一语音/显示触发连发两次（产物出现「同格重复语音」，见 doc/lessons-learned.md §16）。
        """
        i0 = o14[r0 - 1] + 1 if r0 > 0 else 0
        i1 = o14[r1] + 1
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
            if op == 0x14:
                # 池序号全量重算：插入行的 `14.id` 必须改写为新槽序。原版行号与
                # 新槽序只在"插入块紧邻其原位置、且其前无删格"时才恰好相等；一旦
                # 其前有删格，沿用原号就会与宿主侧已重排的号位撞号，而引擎按 id
                # 索引 zh-CN 覆盖层 ⇒ 撞号处及其后的中文整段错位
                # （2026-10-06 复验 D2：9 脚本 / 1,435 槽）。长度不变，不影响 rel/q。
                ops2 = struct.pack('<H', pool) + ops2[2:]
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
