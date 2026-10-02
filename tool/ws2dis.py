"""IMHHW (Steam 版) WS2 线性反汇编器 —— 基于引擎自身的操作数格式表。

背景
----
同引擎 C+C 项目那套反汇编器只识别 Cross-Channel 的操作码集合，在本作上有大量解析
失败（158 个脚本只跑通 139 个）。本模块改为使用从引擎二进制 `off_553EC0` 导出的
256 项操作数格式表（`tool/ws2fmt.txt`），因此对本作是**权威**的。

C+C 反汇编器在本作 158 个脚本上只能跑通 139 个（139/158）；
本模块配合「遇 0xff 即停止」规则可跑通 153/158。
剩余 5 个（`CG_PAGE10/12`、`CO1_018`、`CO2_005`、`HUT_005`）含内嵌
菜单/数据表，线性解析不适用。

格式串
----
每个字节是一个操作数类型码，`>= 0x80` 为终止符：
  0=u8(1) 1=u16(2) 2=u16(2) 3=u32(4) 4=u32(4) 5=f32(4)
  6=str 7=变长块 8=0B 9=str 10=str

用法
----
    python tool/ws2dis.py <file.ws2>            # 反汇编解码后的脚本
    python tool/ws2dis.py --arc <Rio.arc>       # 扫全部脚本并报告解析率
"""
import pathlib
import re
import sys

FMT_TXT = pathlib.Path(__file__).with_name("ws2fmt.txt")

TYPE_SIZE = {0: 1, 1: 2, 2: 2, 3: 4, 4: 4, 5: 4, 8: 0}
STR_TYPES = (6, 9, 10)

# 脚本文件结构：代码 ... 0xff(END) + 8 字节固定尾部
OP_END = 0xFF
TAIL_LEN = 8


def load_formats(path=FMT_TXT):
    fmts = {}
    for line in pathlib.Path(path).read_text().splitlines():
        m = re.match(r"^0x([0-9a-f]{2})\s+(.*)$", line.strip())
        if not m:
            continue
        fmts[int(m.group(1), 16)] = [int(x, 16) for x in m.group(2).split()]
    return fmts


FORMATS = load_formats()


def _strlen(data, pos):
    end = data.find(b"\x00", pos)
    if end < 0:
        raise ValueError("unterminated string at 0x%x" % pos)
    return end - pos + 1


def instruction_size(data, pos):
    """返回 (size, opcode)；size 含操作码本身。"""
    op = data[pos]
    fmt = FORMATS.get(op)
    p = pos + 1
    if fmt is None:
        return 1, op
    i = 0
    n = len(fmt)
    while i < n:
        c = fmt[i]
        if c >= 0x80:
            break
        if c == 7:
            # 变长块：读 1 字节计数，再重复下一个类型码 count 次
            if p >= len(data):
                raise ValueError("trunc var block at 0x%x" % pos)
            count = data[p]
            p += 1
            rep = fmt[i + 1] if i + 1 < n else 0
            i += 2
            for _ in range(count):
                if rep in STR_TYPES:
                    p += _strlen(data, p)
                    p += 1  # 引擎对 6/9 额外吃掉 1 字节
                else:
                    p += TYPE_SIZE.get(rep, 0)
            continue
        if c in STR_TYPES:
            p += _strlen(data, p)
        else:
            p += TYPE_SIZE.get(c, 0)
        i += 1
    return p - pos, op


def disassemble(data, stop_at_end=True):
    """线性反汇编。

    返回 (instrs, ok)：instrs 为 [(off, op, size, operand_bytes)]。
    ok=True 表示「恰好在 0xff 处结束且尾部 == 8 字节」——即线性解析自洽。
    """
    out = []
    pos = 0
    n = len(data)
    while pos < n:
        sz, op = instruction_size(data, pos)
        out.append((pos, op, sz, data[pos + 1 : pos + sz]))
        pos += sz
        if stop_at_end and op == OP_END:
            return out, (n - pos == TAIL_LEN)
    return out, False


def disassemble_strict(data):
    """只要指令列表（向后兼容）。"""
    return disassemble(data)[0]


def _main():
    args = sys.argv[1:]
    if args and args[0] == "--arc":
        sys.path.insert(0, str(pathlib.Path(__file__).parent))
        import arcbuild
        from ws2 import decode

        ok = bad = 0
        badlist = []
        for name, raw in arcbuild.read_raw(args[1]):
            nm = name.decode("utf-16-le", "replace")
            if not nm.lower().endswith(".ws2"):
                continue
            instrs, good = disassemble(decode(raw))
            if good:
                ok += 1
            else:
                bad += 1
                badlist.append(nm)
        print("ok=%d bad=%d" % (ok, bad))
        for nm in badlist:
            print("  FAIL", nm)
        return

    data = pathlib.Path(args[0]).read_bytes()
    instrs, ok = disassemble(data)
    for off, op, sz, ops in instrs:
        print("0x%04x  op=0x%02x sz=%-3d ops=%s" % (off, op, sz, ops.hex(" ")))
    print("tail ok:", ok)


if __name__ == "__main__":
    _main()
