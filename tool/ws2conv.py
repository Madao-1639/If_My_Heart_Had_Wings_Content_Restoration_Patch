# -*- coding: utf-8 -*-
"""原版 WS2 → Steam WS2 编码转换（公共工序，本体线与 L4 共用）。

两版引擎各自带一张 256 项操作数格式表；本模块负责：
  1. 从原版 AdvHD.exe 提取原版格式表（自校验 entry[0x21]）；
  2. 按表线性解析原版脚本；
  3. 应用两版格式差（CONV，9 条）并重定基携带「解码流内绝对偏移」的跳转
     （0x01.a / 0x01.b / 0x02 / 0x06）；
  4. 用 Steam 表（tool/ws2dis.FORMATS）回读校验。

格式差依据 = 两版 256 项格式表**全量差分**：实质内容差恰 9 条，
其余差异为终止符 0xff 提取约定差或 Steam 独有新 opcode（原版脚本不会发出，
Steam 表回读会兜底拦截）。实测出现面见 convert_sl_ws2.py 的历史输出。

⚠️ 0x01.a/b、0x02、0x06 的目标值是**解码流内的绝对字节偏移**（真实 Steam 脚本
2116/2116 个可解析目标全部对齐到指令起点）；值为 0 表示「无此目标」，必须跳过。
`a != 0` 时优先于 `b`（引擎 sub_459DA0）。

⚠️ `tool/ws2dis.disassemble()` 的 `ok` 标志只校验尾部长度，查不出流中部失步，
不能当「可解析」凭证——一切以本模块 parse + Steam 表回读为准。
"""
import struct

from tool import ws2dis

ORIG_TABLE_OFF = 0x1212c0          # 原版 exe 内 256 项格式指针表的文件偏移

# ('mid1', n): 操作数倒数第 n 字节前插 1 字节 0x00
# ('end1', None): 操作数尾插 1 字节 0x00
# ('end4', None): 操作数尾插 4 字节 0x00（f32 0.0）
CONV = {
    0x11: ('mid1', 4),
    0x14: ('end1', None),
    0x15: ('end1', None),
    0x16: ('end1', None),
    0x1c: ('end1', None),
    0x1e: ('end4', None),
    0x28: ('end4', None),
    0x35: ('end1', None),
    0x56: ('end4', None),
}

# op → 携带「解码流内绝对偏移」的 u32 字段在操作数内的偏移列表
REBASE_OPS = {0x01: (7, 11), 0x02: (0,), 0x06: (0,)}


# ── 跨引擎「标志字节」归一（只改取值、不改长度；坐标偏移全不动）────────────
# 两侧工具链对 `0x46`／`0x47` 这两个同族指令的取值**零交叉**：原版 `0x46 ∈ {0x00,0x80}`、
# `0x47.B ∈ {0x00,0x80}`；Steam `0x46 ∈ {0x00,0xf0}`、`0x47.B ∈ {0x00,0x10,0xc0}`。
# 带着原版取值进 Steam 引擎会落在目标引擎自身的词表外：`0x46` 欠绑定子层槽（未重绑的槽保留
# 上一次显示的子图 ⇒ 立绘残留）、`0x47` 的参数来源位失配（动画照跑、终点不对，不报错不闪退）。
# 语义与依据见 doc/engine-mechanics.md「动画组的工作机制」与「0x47 Effect1 语义与跨引擎标志换算」。

def norm_op46_flag(ops):
    """`0x46` 子层槽绑定标志：原版 `0x80` → Steam `0xf0`（幂等）。

    操作数布局 `<通道>\\0` ＋ u16 ＋ **u8 标志** ＋ 4×f32（`tool/ws2fmt.txt` 的 `0x46`），
    所以标志在首个 NUL 之后的第 3 个字节。
    """
    i = ops.find(b'\x00')
    if 0 <= i and len(ops) > i + 3 and ops[i + 3] == 0x80:
        return ops[:i + 3] + b'\xf0' + ops[i + 4:]
    return ops


def norm_op47_flag(ops, last_drag_type):
    """`0x47` Effect1 的参数来源标志：原版 `0x80` → Steam `0x10` / `0xc0`（幂等）。

    布局 `<通道>\\0` ＋ `<特效名>\\0` ＋ u16 sel ＋ u8 A ＋ **u8 B(bit7=参数走变量)** ＋ …，
    所以 B 在**第二个** NUL 之后第 5 个字节（`ws2fmt.txt` 的 `0x47 = 06 08 | 06 08 | 01 00 | 00 05…`：
    u16 sel 占 2 字节后是 A，再下一个就是 B）。

    `B` 的取值**跟随流内上一条 `0x45` 的 `type`**：type 6（复位/缩放，字面）⇒ `0x10`；
    其余（0/2…，参数走变量）⇒ `0xc0`。所以本函数必须按脚本整体走一遍（`norm_flags`），
    不能逐条独立调用。依据：参考实现 `advanced_hd` 工具链的 update 规则，以及两侧同位置
    1,404 条样本 99.3% 命中。
    """
    i = ops.find(b'\x00')
    j = ops.find(b'\x00', i + 1) if i >= 0 else -1
    if j < 0 or len(ops) <= j + 4 or ops[j + 4] != 0x80:
        return ops
    return ops[:j + 4] + (b'\x10' if last_drag_type == 6 else b'\xc0') + ops[j + 5:]


def norm_flags(instrs):
    """整表标志字节归一（`0x46` + `0x47`，长度不变 ⇒ 偏移可直接沿用）。

    返回新的 `[(op, ops)]`；对已是 Steam 取值的流是恒等变换（幂等）。
    `0x47` 的取值依赖**流内前文**（上一条 `0x45` 的 type），所以必须整表走。
    """
    out = []
    drag = None
    for op, ops in instrs:
        if op == 0x46:
            ops = norm_op46_flag(ops)
        elif op == 0x45:
            k = ops.find(b'\x00')
            if k >= 0 and len(ops) >= k + 3:
                drag = int.from_bytes(ops[k + 1:k + 3], 'little', signed=True)
        elif op == 0x47:
            ops = norm_op47_flag(ops, drag)
        out.append((op, ops))
    return out


def load_orig_formats(orig_dir):
    """从原版 exe 提取 256 项操作数格式表，返回 {op: [type codes]}（不含 0xff）。"""
    from pathlib import Path
    b = (Path(orig_dir) / 'AdvHD.exe').read_bytes()
    e = struct.unpack_from('<I', b, 0x3c)[0]
    nsec = struct.unpack_from('<H', b, e + 6)[0]
    optsize = struct.unpack_from('<H', b, e + 20)[0]
    imagebase = struct.unpack_from('<I', b, e + 24 + 28)[0]
    secs = []
    off = e + 24 + optsize
    for i in range(nsec):
        _, vsize, vaddr, rawsize, rawoff = struct.unpack_from('<8sIIII', b, off + i * 40)
        secs.append((vaddr, max(vsize, rawsize), rawoff, rawsize))

    def va2off(va):
        rva = va - imagebase
        for vaddr, vsize, rawoff, rawsize in secs:
            if vaddr <= rva < vaddr + vsize:
                o = rawoff + (rva - vaddr)
                if o < rawoff + rawsize:
                    return o
        return None

    ptr21 = struct.unpack_from('<I', b, ORIG_TABLE_OFF + 4 * 0x21)[0]
    o21 = va2off(ptr21)
    assert b[o21:o21 + 6] == bytes([0x06, 0x08, 0x01, 0x01, 0x01, 0xff]), \
        '原版格式表基址校验失败: op21 @%#x' % ptr21

    fmts = {}
    for op in range(256):
        ptr = struct.unpack_from('<I', b, ORIG_TABLE_OFF + 4 * op)[0]
        if not ptr:
            continue
        o = va2off(ptr)
        assert o is not None, (op, hex(ptr))
        fmt = []
        i = 0
        while b[o + i] != 0xff:
            fmt.append(b[o + i])
            i += 1
        fmts[op] = fmt
    # 0x1b 的表项描述符抽取不全（只出 [0]，丢字符串字段）：原版脚本里
    # `1b 00 "好きです"` 这类带内嵌字符串的写法会让线性解析在字符串首字节上
    # 撞「tableless op」（CO1_016_A 首次触发；此前多数需解析脚本
    # 均不含 0x1b 故未暴露）。经验修补 = steam 侧 0x49 的形状加前导 u8
    # （[0,6,8,6,8,10,8]）；判据 = 全库 158 个 orig 脚本线性解析全部自洽
    # （0xff 恰收尾 + 8 字节尾）、其余脚本的 0x14 计数一个不变、CO1_016_A
    # 该串正确解出「好きです」（对应 steam 侧同位 "I like it"）。
    # 0x1b 仍无 CONV 规则 ⇒ 含 0x1b 的 orig span 不得进插入区间
    # （CO1_016_A 的 0x1b 在末行 span，正常还原不触及）。
    fmts[0x1b] = [0, 6, 8, 6, 8, 10, 8]
    return fmts


def parse(data, fmts):
    """按格式表线性解析。

    返回 (instrs, tail)：instrs = [(op, operand_bytes)]（含末尾 0xff），
    tail = 0xff 之后的 8 字节固定尾部（重建时必须原样附回）。
    """
    pos, instrs = 0, []
    n = len(data)
    while pos < n:
        op = data[pos]
        fmt = fmts.get(op)
        p = pos + 1
        if fmt is None:
            assert op == 0xff and n - pos == 9, 'unexpected tableless op %#x @%#x' % (op, pos)
            instrs.append((op, b''))
            return instrs, data[pos + 1:]
        i = 0
        m = len(fmt)
        while i < m:
            c = fmt[i]
            if c >= 0x80:
                break
            if c == 7:
                cnt = data[p]
                p += 1
                rep = fmt[i + 1]
                i += 2
                for _ in range(cnt):
                    if rep in ws2dis.STR_TYPES:
                        p += ws2dis._strlen(data, p) + 1
                    else:
                        p += ws2dis.TYPE_SIZE.get(rep, 0)
                continue
            if c in ws2dis.STR_TYPES:
                p += ws2dis._strlen(data, p)
            else:
                p += ws2dis.TYPE_SIZE.get(c, 0)
            i += 1
        instrs.append((op, data[pos + 1:p]))
        pos = p
        if op == 0xff:
            assert n - pos == 8, 'tail must be 8 bytes, got %d' % (n - pos)
            return instrs, data[pos:]
    raise AssertionError('parse ran off end without 0xff')


def convert(instrs):
    """应用格式差转换，并重定基块内跳转（跨块目标由调用方二次回写）。

    返回 [(op, ops)]。转换逐指令确定新尺寸，故先建「原偏移→新偏移」映射，
    再发出并把 0x01.a/0x01.b/0x02/0x06 的非零目标改写为块内新偏移。
    ⚠️ 目标若指向**本块之外**（如 H 场景退出口指向脚本尾），不在 orig_offs 里，
    会触发 assert —— 此类块必须由调用方拆分或改走 writer 的跨块回写。
    """
    def new_size(op, ops):
        rule = CONV.get(op)
        if rule is None:
            return 1 + len(ops)
        return 1 + len(ops) + (1 if rule[0] in ('mid1', 'end1') else 4)

    new_offs = {}
    orig_pos = new_pos = 0
    for op, ops in instrs:
        new_offs[orig_pos] = new_pos
        orig_pos += 1 + len(ops)
        new_pos += new_size(op, ops)

    out = []
    for op, ops in instrs:
        rule = CONV.get(op)
        if rule is not None:
            kind, tail = rule
            if kind == 'mid1':
                assert len(ops) >= tail
                ops = ops[:-tail] + b'\x00' + ops[-tail:]
            elif kind == 'end1':
                ops = ops + b'\x00'
            else:
                ops = ops + b'\x00\x00\x00\x00'
        for k in REBASE_OPS.get(op, ()):
            v = struct.unpack_from('<I', ops, k)[0]
            if v == 0:
                continue
            assert v in new_offs, \
                'op %#x field %#x target %#x not at an instruction start' % (op, k, v)
            ops = ops[:k] + struct.pack('<I', new_offs[v]) + ops[k + 4:]
        out.append((op, ops))
    return out


def emit(instrs, tail):
    return b''.join(bytes([op]) + ops for op, ops in instrs) + tail


def convert_script(raw, orig_dir):
    """整脚本转换（A-1 / SL 用）：原版编码字节 → Steam 编码字节，含回读校验。

    两步：① `convert()` 应用格式差并重定基；② `norm_flags()` 归化 `0x46`/`0x47` 的
    跨引擎标志字节（长度不变，不影响已算好的偏移）。
    """
    from tool import ws2
    d = ws2.decode(raw)
    instrs, tail = parse(d, load_orig_formats(orig_dir))
    conv = norm_flags(convert(instrs))
    out_decoded = emit(conv, tail)
    back, back_tail = parse(out_decoded, ws2dis.FORMATS)
    assert len(back) == len(conv), 'instruction count changed: %d -> %d' % (len(instrs), len(back))
    assert [op for op, _ in back] == [op for op, _ in conv], 'opcode sequence changed'
    assert [ops for _, ops in back] == [ops for _, ops in conv], 'operand roundtrip mismatch'
    assert back_tail == tail, 'tail changed'
    starts = set()
    p = 0
    for op, ops in conv:
        starts.add(p)
        p += 1 + len(ops)
    for op, ops in conv:
        for k in REBASE_OPS.get(op, ()):
            v = struct.unpack_from('<I', ops, k)[0]
            if v == 0:
                continue
            assert v in starts, \
                'rebased target %#x (op %#x field %#x) not at instruction start' % (v, op, k)
    return ws2.encode(out_decoded)


# ── 脚本头部前缀插指令（跨脚本接缝的入口清屏用）──────────────────────────────
CLEAR_OP = 0x37


def insert_head_clear(decoded, chans):
    """在**解码流**最前面插入 `37 <通道>\0` 清屏，并把所有绝对偏移字段整体重定基。

    用途：跨脚本接缝的入口状态规范化（见 tool/perfsync.py「跨脚本接缝」）。清屏是
    **幂等**的（通道不在屏时清它是空操作），所以多入口（剧情前序／回想列表列表页）
    共用同一个前缀清屏不需要分来源；重复清只浪费 1 条指令，不影响画面。

    `decoded` 是**解码后**的 Steam 编码流（`convert_script` 的产物再 `ws2.decode`）。
    返回 `(new_decoded, n_rebased)`；`chans` 为空时原样返回。

    硬约束（调用方负责断言，本函数内部能查的都查了）：
      1. 重定基后每个非零目标都必须落在**指令起点**；
      2. 反汇编自洽；
      3. 末尾 8 字节尾表**不变**（`0x14`/`0x0f` 条数没变）；
      4. 只发 `0x37`，**不携带任何 `0x04` 成就钩子**（不新增成就触发点）。
    """
    chans = [c for c in (chans or [])]
    if not chans:
        return decoded, 0
    ins = b''.join(bytes([CLEAR_OP]) + c.encode('ascii') + b'\x00' for c in chans)
    n = len(ins)
    out = bytearray(ins + decoded)
    insts, _ok = ws2dis.disassemble(bytes(out))
    rebased = 0
    for off, op, sz, _ops in insts:
        ks = REBASE_OPS.get(op)
        if not ks:
            continue
        base = off + 1
        for k in ks:
            if sz - 1 < k + 4:
                continue
            v = struct.unpack_from('<I', out, base + k)[0]
            if v == 0:                     # 0 = 无此目标，必须跳过
                continue
            struct.pack_into('<I', out, base + k, v + n)
            rebased += 1
    new = bytes(out)
    # ── 自校验 ──
    insts2, ok2 = ws2dis.disassemble(new)
    assert ok2, 'insert_head_clear: 插入后反汇编不自洽'
    starts = {off for off, _op, _sz, _o in insts2}
    for off, op, sz, ops2 in insts2:
        for k in REBASE_OPS.get(op, ()):
            if sz - 1 < k + 4:
                continue
            v = struct.unpack_from('<I', ops2, k)[0]
            assert not v or v in starts, \
                'insert_head_clear: 重定基目标 %#x（op %#x @%#x）不落在指令起点' % (v, op, off)
    assert new[-8:] == decoded[-8:], 'insert_head_clear: 尾表被改动'
    assert sum(1 for _o, op, _s, _p in insts2 if op == 0x14) == \
           sum(1 for _o, op, _s, _p in ws2dis.disassemble(decoded)[0] if op == 0x14), \
        'insert_head_clear: 0x14 条数变化（.lng 对位会错）'
    return new, rebased
