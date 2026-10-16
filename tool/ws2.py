"""WS2 剧本脚本编解码 + 成就调用注入。

混淆方式是逐字节 rotate-left-6（已验证可逆，解码后暴露出 ASCII 操作码/操作数，
如脚本名、CG 文件名、LAYER_ORDER 等关键字——详见 doc/file-formats.md）。

已确认的相关操作码（基于对 Steam 版全部 159 个 Rio.arc 脚本的实测）：

    0x33  <slot>\0 <FILE.PNG>\0 0x01 0x01     在背景/CG 槏位显示一张 PNG
    0x0b  <u16 var> 0x01                      设置变量（推测为图库编号/差分编号）
    0x04  <NAME>\0                            调用另一个脚本

每次 CG 显示后必定紧跟两个 0x0b 变量设置操作，这两个操作在 Steam 版与原版脚本中
都存在——它们是显示 CG 本身固有的部分，与成就系统无关。逐字节 diff 同一场景在
两个版本的脚本，Steam 版精确多出 16 字节：

    ...0101  0b <u16 A> 01  0b <u16 B> 01  [04 "CG_ACHIEVEMENT" 00]  ...
             |<---- 两版本共有 ---->|      |<----- 仅 Steam 版 ----->|

已对 Steam 版全部脚本验证：每一处 0x33 CG 显示指令之后都跟着这条成就调用
（920 处显示，920 处调用，覆盖率 100%）。因此注入逻辑只需在既有变量对之后
插入这 16 字节调用，绝不重新生成/计算变量对本身的数值——那两个值是显示 CG
的固有数据，应直接复用脚本中已经写好的值。
"""
import re
import struct

ACH_NAME = b'CG_ACHIEVEMENT'
ACH_CALL = b'\x04' + ACH_NAME + b'\x00'

# 0x33 <slot> 00 <STEM>.PNG 00 01 01 后紧跟固有的 id 变量对。
DISPLAY = re.compile(
    rb'\x33([A-Za-z0-9_]{2,12})\x00([A-Za-z0-9_]+)\.PNG\x00\x01\x01'
    rb'\x0b(..)\x01\x0b(..)\x01', re.S)


# ── 文件末尾 8 字节「明文尾表」 ────────────────────────────────────────────────
# 文件**末尾 8 字节**是不参与混淆的明文表 `[u32 消息数][u32 选项条目数]`
# （0x14 条数 / 0x0f 的 entry 数）。引擎**加载脚本时**读它（`data[size-8]`），
# 用来给「已读消息位图」（存档目录 `MessageFlag.dat`）分配容量
# `(消息数 + 选项条目数 + 7) / 8` 字节；而写位函数 `bitmap[idx>>3] |= 1<<(idx&7)`
# **不做边界检查** ⇒ 尾表小于脚本真实消息数时，高位下标直接写到相邻堆块上，
# 延迟到某次 free 被堆校验抓到 ⇒ `0xc0000374` 概率性闪退（不是崩在写位处）。
# ⇒ **任何改变 0x14 / 0x0f 条数的改动都必须同步重写这 8 字节**，且要在
#   `encode()` **之后**写（写成明文；先写会被旋转成垃圾）。
# （机制与跨作验证见 GalRev `docs/engines/advhd/file-formats.md`「末尾 8 字节」
#   与 `save-system.md`「MessageFlag.dat」。）
TAIL_LEN = 8


def read_tail_counts(raw):
    """读原始成员末尾 8 字节 → (消息数, 选项条目数)。"""
    if len(raw) < TAIL_LEN:
        raise ValueError('ws2 too short for a tail table (%d bytes)' % len(raw))
    return struct.unpack('<II', raw[-TAIL_LEN:])


def tail_counts(decoded):
    """数解码流里的 (0x14 指令数, 0x0f 的 entry 数)。"""
    from tool import ws2dis
    msgs = choices = 0
    for _off, op, _sz, ops in ws2dis.disassemble(decoded)[0]:
        if op == 0x14:
            msgs += 1
        elif op == 0x0f and ops:
            choices += ops[0]          # 变长块首字节 = 条目数（格式表 0x0f = `00 ff`）
    return msgs, choices


def set_tail_counts(raw, counts):
    """重写明文尾表；**必须在 `encode()` 之后调用**。"""
    return raw[:-TAIL_LEN] + struct.pack('<II', int(counts[0]), int(counts[1]))


def fix_tail_after_rewrite(raw_new, decoded_new, raw_base, decoded_base):
    """按「基线约定」自适应重写改写后脚本的尾表。

    基线自身两侧一致（尾表 == 实算）时写实算值；基线自身就不一致时
    （本作 Steam 基线有 3 个脚本如此，见 `check_tails`）按增量平移，
    以免把基线自己的偏离当成新破坏。
    """
    base_tail = read_tail_counts(raw_base)
    base_cnt = tail_counts(decoded_base)
    new_cnt = tail_counts(decoded_new)
    if base_cnt == base_tail:
        want = new_cnt
    else:
        want = (base_tail[0] + (new_cnt[0] - base_cnt[0]),
                base_tail[1] + (new_cnt[1] - base_cnt[1]))
    return set_tail_counts(raw_new, want), want


def check_tails(members, base_members=None):
    """逐成员查尾表。返回 (ok_list, bad_list)。

    bad_list 元素为 (成员名, 实算, 尾表)；给 `base_members` 时只报
    「基线本来没问题、产物却坏了」的成员（真正的新增破坏）。
    """
    ok, bad = [], []
    for name, raw in members.items():
        if not name.lower().endswith('.ws2'):
            continue
        cnt = tail_counts(decode(raw))
        tail = read_tail_counts(raw)
        if cnt == tail:
            ok.append(name)
            continue
        if base_members and name in base_members:
            if tail_counts(decode(base_members[name])) != read_tail_counts(base_members[name]):
                continue                       # 基线自身就偏离 ⇒ 不计新增破坏
        bad.append((name, cnt, tail))
    return ok, bad


def decode(raw):
    """反混淆一个 .ws2 成员（rotate left 6）。"""
    return bytes(((c << 6) | (c >> 2)) & 0xff for c in raw)


def encode(data):
    """重新混淆一个 .ws2 成员（逆操作：rotate right 6，等价于 rotate left 2）。"""
    return bytes(((c << 2) | (c >> 6)) & 0xff for c in data)


def find_display_sites(data):
    """遍历每一处 CG 显示操作，产出 (end_offset, cg_stem, has_call)。

    end_offset 指向固有 id 变量对结束处，正是插入成就调用的位置。
    """
    for m in DISPLAY.finditer(data):
        has_call = data[m.end():m.end() + len(ACH_CALL)] == ACH_CALL
        yield m.end(), m.group(2).decode('ascii'), has_call


def inject(raw):
    """在每一处缺少成就调用的 CG 显示后插入该调用。

    返回 (new_raw, injected_count)。只拼接 16 字节调用，脚本中已有的固有 id
    变量对保持字节不变，复用其中已有的 CG id，不重新计算。
    """
    data = decode(raw)
    out = bytearray()
    cursor = 0
    injected = 0
    for end, _stem, has_call in find_display_sites(data):
        if has_call:
            continue
        out += data[cursor:end]
        out += ACH_CALL
        cursor = end
        injected += 1
    out += data[cursor:]
    return encode(bytes(out)), injected
