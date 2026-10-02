# -*- coding: utf-8 -*-
"""原版 WS2 → Steam WS2 编码转换（公共工序，本体线与 L4 共用）。

两版引擎各自带一张 256 项操作数格式表；本模块负责：
  1. 从原版 AdvHD.exe 提取原版格式表（自校验 entry[0x21]）；
  2. 按表线性解析原版脚本；
  3. 应用两版格式差（CONV，9 条）并重定基携带「解码流内绝对偏移」的跳转
     （0x01.a / 0x01.b / 0x02 / 0x06）；
  4. 用 Steam 表（tool/ws2dis.FORMATS）回读校验。

格式差依据 = 两版 256 项格式表**全量差分**（2026-10-02）：实质内容差恰 9 条，
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
    """整脚本转换（A-1 / SL 用）：原版编码字节 → Steam 编码字节，含回读校验。"""
    from tool import ws2
    d = ws2.decode(raw)
    instrs, tail = parse(d, load_orig_formats(orig_dir))
    conv = convert(instrs)
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
