"""ARC 归档读写，保留成员名的原始字节。

头部为 8 字节 (count: u32, table_size: u32)。条目表紧随头部，每条 8 字节
(size: u32, rel_offset: u32) + UTF-16LE 文件名 + 双 NUL 终止符。offset 字段
是相对 `8 + table_size` 的相对偏移，不是文件绝对偏移——已对 Rio.arc/Script.arc
等归档实测确认该假设成立（详见 doc/file-formats.md）。
"""
import struct
from pathlib import Path

HEADER = struct.Struct('<II')
ENTRY = struct.Struct('<II')


def read_raw(path):
    """返回 [(name_bytes, data)]，name_bytes 为磁盘原始字节（未解码）。"""
    blob = Path(path).read_bytes()
    count, table_size = HEADER.unpack_from(blob, 0)
    data_start = 8 + table_size
    out = []
    off = 8
    for _ in range(count):
        size, rel = ENTRY.unpack_from(blob, off)
        off += 8
        start = off
        while blob[off:off + 2] != b'\0\0':
            off += 2
        name_bytes = blob[start:off]
        off += 2
        begin = data_start + rel
        data = blob[begin:begin + size]
        if len(data) != size:
            raise ValueError('truncated member %r in %s' % (name_bytes, path))
        out.append((name_bytes, data))
    return out


def write_arc(members, output_path):
    """写入归档，members 为 [(name_bytes, data)]，offset 自动计算为相对偏移。"""
    table_size = sum(8 + len(n) + 2 for n, _ in members)
    table = bytearray()
    rel = 0
    for name_bytes, data in members:
        table += ENTRY.pack(len(data), rel)
        table += name_bytes + b'\0\0'
        rel += len(data)
    if len(table) != table_size:
        raise AssertionError('table size mismatch')

    with open(output_path, 'wb') as fh:
        fh.write(HEADER.pack(len(members), table_size))
        fh.write(table)
        for _, data in members:
            fh.write(data)
    return Path(output_path).stat().st_size


def verify(path, expect_count=None):
    """重新读取归档并校验所有成员均在文件边界内；检测表尾多余 null padding。"""
    blob = Path(path).read_bytes()
    count, table_size = HEADER.unpack_from(blob, 0)
    data_start = 8 + table_size
    off, seen, end = 8, 0, data_start
    for _ in range(count):
        size, rel = ENTRY.unpack_from(blob, off)
        off += 8
        while blob[off:off + 2] != b'\0\0':
            off += 2
        off += 2
        stop = data_start + rel + size
        if stop > len(blob):
            raise ValueError('member overruns file: %d > %d' % (stop, len(blob)))
        end = max(end, stop)
        seen += 1
    if seen != count:
        raise ValueError('entry count mismatch')
    if expect_count is not None and count != expect_count:
        raise ValueError('expected %d members, got %d' % (expect_count, count))

    if end < len(blob) and blob[data_start:data_start + 2] == b'\0\0':
        raise ValueError(
            'spurious null padding at table end (position %d). '
            'Run normalize_arc_padding() to remove it' % data_start
        )

    return count, len(blob), end


def normalize_arc_padding(path):
    """清除表尾多余 null padding，重写为规范形式。"""
    members = read_raw(path)
    write_arc(members, path)
    return Path(path).stat().st_size
