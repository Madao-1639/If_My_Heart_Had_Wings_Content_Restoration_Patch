"""原版（非 Steam）WS2 脚本的文本行提取。

一个脚本的"文本行"（对齐语料时的 A 行）= 脚本内所有会被显示层消费的字符串，
按字节偏移排序，四类：

  dlg   \\x14 <idx:u16> <flag=0> <speaker\\0> <text>%K%P|%%K|%P\\x00  对白
  ctrl  同上但 speaker 为空（清屏行，text 恰为 %P）
  name  \\x15 %LC<名>\\x00  角色名标记
  menu  \\x0f 选项块内 <id:u16> <标签>\\x00 ... \\x07<目标脚本>\\x00
  flag  FLAG_CHECK 变量表内 <id:u16> <标签>\\x00

`crc` 是引擎口径的查表键：cp932 解码 → UTF-16LE 字节 → CRC32（有符号 int32）。

噪声排除（doc/lessons-learned.md）：
  - \\x14 巧合命中 LAYER_ORDER 等二进制块：flag!=0、speaker 不是 char/空、
    text 含 NUL、空 speaker 但 text 不是 %P 的候选全部丢弃。
  - FLAG_CHECK 扫描：真标签必为 cp932 可解码且含非 ASCII 字符（全是人名/
    变量提示语）；纯 ASCII 的是二进制巧合命中，会让 CO1_018 这类脚本的槽位
    数虚增到 3 万余。
"""
import collections
import os
import re
import struct
import zlib
from pathlib import Path

# 原版素材与民汉语料表都不进版本库：路径由环境变量给出（用途与性质见
# doc/restoration-targets.md §素材来源），未设置时为 None，由调用方拒绝并提示。
IFMH_ORIG_DIR = 'IFMH_ORIG_DIR'
IFMH_CORPUS_TABLE = 'IFMH_CORPUS_TABLE'


def _env_path(var):
    value = os.environ.get(var)
    return Path(value) if value else None


DEFAULT_ORIG_DIR = _env_path(IFMH_ORIG_DIR)
DEFAULT_TABLE = _env_path(IFMH_CORPUS_TABLE)

# RIO/ 裸目录中与 Rio.arc 同名的构建残留（以 Rio.arc 内版本为准），
# 以及无文本的 start.ws2
RIO_SKIP = {'CO1_001', 'CO1_002', 'CO1_003', 'CO1_015', 'HUT_004', 'HUT_005', 'start'}

LINE14_SCAN = re.compile(rb'\x14..(..)', re.DOTALL)
TEXT_END = re.compile(rb'((?:[\x80-\xff\x00-\x7f])*?)(%K%P|%K(?!%P)|(?<!%K)%P)\x00')
NAME_MARKER = re.compile(rb'\x15(%LC[\x80-\xff\x20-\x7f]+?)\x00', re.DOTALL)
FLAGCHECK_HEAD = re.compile(rb'FLAG_CHECK\x00\x0f(.)', re.DOTALL)


def crc32_signed(text_bytes):
    """引擎口径的文本 CRC32：cp932 解码 → UTF-16LE → CRC32（有符号 int32）。"""
    try:
        u = zlib.crc32(text_bytes.decode('cp932').encode('utf-16le')) & 0xffffffff
    except UnicodeDecodeError:
        return None
    return u - 0x100000000 if u >= 0x80000000 else u


def ws2_decode(data):
    from tool import ws2 as ws2_mod
    return ws2_mod.decode(data)


def _read14(decoded, j):
    """偏移 j 处的真 \\x14 行 → (idx, speaker, text bytes)；噪声返回 None。"""
    if struct.unpack_from('<H', decoded, j + 3)[0] != 0:
        return None
    idx = struct.unpack_from('<H', decoded, j + 1)[0]
    z = decoded.find(b'\x00', j + 5)
    if z < 0:
        return None
    speaker = decoded[j + 5:z]
    if speaker not in (b'char', b''):
        return None
    mm = TEXT_END.match(decoded, z + 1)
    if not mm:
        return None
    text = decoded[z + 1:mm.end(2)]
    if b'\x00' in text:
        return None
    if speaker == b'' and text != b'%P':
        return None
    return idx, speaker, text


def _menu_entries(decoded):
    """\\x0f 选项块 → [(label 偏移, id, 标签, 目标脚本)]，按整块校验。"""
    out = []
    pos = 0
    while True:
        j = decoded.find(b'\x0f', pos)
        if j < 0 or j + 2 > len(decoded):
            break
        n = decoded[j + 1]
        p = j + 2
        entries = []
        ok = n > 0
        for _ in range(n):
            if p + 2 > len(decoded):
                ok = False
                break
            eid = struct.unpack_from('<H', decoded, p)[0]
            z = decoded.find(b'\x00', p + 2)
            if z < 0 or z + 4 >= len(decoded) or decoded[z + 4] != 0x07:
                ok = False
                break
            zend = decoded.find(b'\x00', z + 5)
            if zend < 0:
                ok = False
                break
            try:
                label = decoded[p + 2:z].decode('cp932')
            except UnicodeDecodeError:
                ok = False
                break
            entries.append((p, eid, label, decoded[z + 5:zend].decode('cp932', 'replace')))
            p = zend + 1
        if ok:
            out.extend(entries)
            pos = p
        else:
            pos = j + 1
    return out


def _flagcheck_entries(decoded):
    """FLAG_CHECK 变量表 → [(label 偏移, id, 标签)]，只保留真标签。"""
    out = []
    for m in FLAGCHECK_HEAD.finditer(decoded):
        n = m.group(1)[0]
        p = m.end()
        for _ in range(n):
            if p + 2 > len(decoded):
                break
            eid = int.from_bytes(decoded[p:p + 2], 'little')
            z = decoded.find(b'\x00', p + 2)
            if z < 0:
                break
            raw = decoded[p + 2:z]
            try:
                label = raw.decode('cp932')
            except UnicodeDecodeError:
                label = None
            if label and any(ord(c) > 0x7F for c in label):
                out.append((p, eid, label))
            p = z + 9
    return out


def script_rows(name, data):
    """单脚本 → A 行列表（按字节偏移，再按 kind 稳定序）。"""
    decoded = ws2_decode(data)
    recs = []
    for m in LINE14_SCAN.finditer(decoded):
        r = _read14(decoded, m.start())
        if r is None:
            continue
        idx, speaker, text = r
        kind = 'ctrl' if speaker == b'' else 'dlg'
        recs.append((m.start(), kind, idx, text.decode('cp932', 'replace'),
                     crc32_signed(text)))
    for m in NAME_MARKER.finditer(decoded):
        raw = m.group(1)
        recs.append((m.start(), 'name', None, raw.decode('cp932', 'replace'),
                     crc32_signed(raw)))
    for off, eid, label, _tgt in _menu_entries(decoded):
        recs.append((off, 'menu', eid, label, crc32_signed(label.encode('cp932'))))
    for off, eid, label in _flagcheck_entries(decoded):
        recs.append((off, 'flag', eid, label, crc32_signed(label.encode('cp932'))))
    recs.sort(key=lambda x: x[0])
    rows = []
    for k, (off, kind, idx, jp, crc) in enumerate(recs):
        rows.append({'script': name, 'seq': k, 'off': off, 'kind': kind,
                     'idx': idx, 'jp': jp, 'crc': crc})
    idxs = [r['idx'] for r in rows if r['kind'] in ('dlg', 'ctrl')]
    dup = [i for i, c in collections.Counter(idxs).items() if c > 1]
    if dup:
        raise AssertionError(f'{name}: duplicate dialogue idx {dup[:8]}')
    return rows


def collect_scripts(orig_dir=DEFAULT_ORIG_DIR):
    """[(脚本名, ws2 字节, 来源)]，按脚本名字典序——即民汉表的铺表序。"""
    from tool import arcbuild
    orig_dir = Path(orig_dir)
    scripts = []
    for nb, data in arcbuild.read_raw(orig_dir / 'Rio.arc'):
        try:
            name = nb.decode('utf-16le')
        except UnicodeDecodeError:
            continue
        if name.lower().endswith('.ws2'):
            scripts.append((name[:-4], data, 'Rio.arc'))
    rio = orig_dir / 'RIO'
    if rio.is_dir():
        for f in sorted(rio.glob('*.ws2')):
            if f.stem not in RIO_SKIP:
                scripts.append((f.stem, f.read_bytes(), 'RIO/'))
    scripts.sort(key=lambda t: t[0])
    return scripts


def all_rows(orig_dir=DEFAULT_ORIG_DIR):
    """全部原版脚本的 A 行，按脚本名字典序拼接。"""
    rows = []
    for name, data, source in collect_scripts(orig_dir):
        for r in script_rows(name, data):
            r['source'] = source
            rows.append(r)
    return rows
