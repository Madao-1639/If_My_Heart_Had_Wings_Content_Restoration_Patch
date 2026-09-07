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
