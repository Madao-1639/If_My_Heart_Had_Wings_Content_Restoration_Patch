# -*- coding: utf-8 -*-
"""CG 解锁对的**编号归属**：解锁对 `(A,B)` 只认 Steam 的编号空间。

## 问题

CG 显示点后恒跟一组解锁位点（见 doc/engine-mechanics.md「成就触发点契约」）：

```
0x33 <槽> <CG.PNG> u8 u8   0b <A> 01   0b <B> 01   [04 CG_ACHIEVEMENT]
```

`CG_PAGE` / `CG_Achievement` 按 `A`/`B` 读**Steam 自己的**条目表与计数阈值。
而原版与 Steam 是**两套独立编号**：两侧同帧的 `(A,B)` 绝大多数不同
（实测同名帧 479 个，`B` 系系统性错开 1–3 号，仅 10 个巧合相同）。

⇒ **原版段的解锁对不能照抄进 Steam 的编号空间**：那会点亮一张完全不相干的画廊条目。
ASFS 侧的定案口径同此：「A/B 必须取自被替换的 Steam 脚本字节，不能拿原版编号冒充」。

## 本模块的判据

`frame_key()` 把图名归一到**帧**（去掉扩展名与末尾 `S`/`B` 分辨率后缀）——
同一帧的 `S`/`B` 是同一张画、共用同一个 `(A,B)`。

`steam_unlock_map()` 给出 Steam 侧的 `帧 → (A,B)`：实测该映射是**严格单射**
（Steam 库 386 个帧、零冲突），所以可以按帧反查。

## 处置规则（产出端与闸共用）

| 情形 | 处置 |
|---|---|
| 原版帧在 Steam 侧**有同帧** | 解锁对**改写为 Steam 的 `(A,B)`**（反查） |
| 原版帧 Steam 侧**没有**（原版独有） | **丢弃**该解锁对——该帧在 Steam 根本没有画廊条目，点亮必然是错的 |

删格／替换区间内属于 **Steam 字节**的解锁对（值本就正确）则一律**保留**，
并提前到该区间前的存活格前缀（解锁是全局置位，与显示点解耦）。
"""
import os
import re
import struct

from tool import arcbuild, paths, ws2, ws2conv, ws2dis

DISPLAY = (0x33, 0x34)
CLEAR = 0x37
ROW = 0x14
FLAG = 0x0B
ACH_CALL = b'CG_ACHIEVEMENT'

_SPLIT = re.compile(r'^(.*?)([SB])?$')


def frame_key(name):
    """图名 → 帧键：去扩展名、去分辨率后缀 `S`/`B`（大小写不敏感）。"""
    if not name:
        return None
    base = name.rsplit('.', 1)[0].upper()
    if len(base) > 1 and base[-1] in ('S', 'B'):
        base = base[:-1]
    return base


def display_unlock_pairs(instrs, lookahead=8):
    """逐 CG 显示点取解锁对 → `[(显示名, A, B)]`（只收 `.PNG` 显示）。

    解锁对＝显示指令之后、下一条显示／正文之前的至多两个 `0b <u16> 01`。
    """
    out, n = [], len(instrs)
    for i, ins in enumerate(instrs):
        op = ins[1] if len(ins) == 4 else ins[0]
        ops = ins[3] if len(ins) == 4 else ins[1]
        if op not in DISPLAY:
            continue
        parts = ops.split(b'\x00')[:2]
        if len(parts) < 2:
            continue
        try:
            name = parts[1].decode('cp932').upper()
        except UnicodeDecodeError:
            continue
        if not name.endswith('.PNG'):
            continue
        a = b = None
        for j in range(i + 1, min(i + 1 + lookahead, n)):
            ins2 = instrs[j]
            op2 = ins2[1] if len(ins2) == 4 else ins2[0]
            ops2 = ins2[3] if len(ins2) == 4 else ins2[1]
            if op2 == FLAG and len(ops2) >= 3:
                v = struct.unpack_from('<H', ops2, 0)[0]
                if a is None:
                    a = v
                else:
                    b = v
            elif op2 in DISPLAY + (ROW,):
                break
        if a is not None and b is not None:
            out.append((name, a, b))
    return out


def _parse(buf, fmt=None):
    if fmt is None:
        return ws2dis.disassemble(ws2.decode(buf))[0]
    ins, _tail = ws2conv.parse(ws2.decode(buf), fmt)
    return ins


_CACHED = None


def default_map():
    """进程内缓存的 Steam 基线映射（`backup/Rio.arc`）。

    映射是**全库共用的只读常量**，不该逐 host 复制进计划表（那会让 `restore_plan.json`
    膨胀到几十万行）。产出端与闸都走这一个入口；`reset_cache()` 供测试/重跑清除。
    """
    global _CACHED
    if _CACHED is None:
        table, conflicts, _skipped = steam_unlock_map(
            os.path.join(paths.STEAM, 'Rio.arc'))
        assert not conflicts,             'Steam 解锁对映射出现冲突（帧 → 多个 (A,B)）：%s' % conflicts[:5]
        _CACHED = table
    return _CACHED


def reset_cache():
    global _CACHED
    _CACHED = None


def steam_unlock_map(backup_rio):
    """Steam 基线 → `{帧键: (A,B)}`（同时返回冲突清单）。

    只读 `backup/Rio.arc`；线性解析不自洽的成员记账跳过。
    """
    table, conflicts, skipped = {}, [], []
    for nb, data in arcbuild.read_raw(backup_rio):
        name = nb.decode('utf-16le', 'replace')
        if not name.lower().endswith('.ws2'):
            continue
        try:
            instrs = _parse(data)
        except Exception:                             # noqa: BLE001 —— 记账不吞
            skipped.append(name)
            continue
        for disp, a, b in display_unlock_pairs(instrs):
            fk = frame_key(disp)
            if fk is None:
                continue
            prev = table.get(fk)
            if prev is not None and prev != (a, b):
                conflicts.append((fk, prev, (a, b)))
            table.setdefault(fk, (a, b))
    return table, conflicts, skipped


def resolve_pair(display_name, steam_map):
    """原版显示名 → 该点应写的 `(A,B)`；`None` ＝ 原版独有帧（应丢弃解锁对）。"""
    return steam_map.get(frame_key(display_name))


def flag_pair_bytes(a, b):
    """把解锁对编成 `0b A 01 0b B 01` 两条指令的字节（Steam 格式）。"""
    return b'\x0b' + struct.pack('<H', a) + b'\x01' + \
           b'\x0b' + struct.pack('<H', b) + b'\x01'


def ach_call_bytes():
    """`04 CG_ACHIEVEMENT 00`（Steam 格式）一条指令的字节。"""
    return b'\x04' + ACH_CALL + b'\x00'
