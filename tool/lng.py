"""ASFoS .lng localization container codec.

Layout (verified byte-exact round-trip on the oozora fan-patch lng set):
    u32                 count
    u16 * count         per-string byte length (includes the trailing NUL pair)
    bytes               count strings, back-to-back, no padding

Each string is UTF-16LE XORed with a single-byte key. Two key families exist:

    0xCE  oozora_CHSpatch 汉化补丁的 lng（该工具最初针对的 311 成员那套）
    0x88  Steam 官方简体中文 `backup/zh-CN/Rio.arc` 内的 95 个逐脚本 .lng
          （2026-09-28 实测：全部条目零解码失败，条目与 Steam 英文脚本台词
          严格对应，另含菜单标签/人名条目；官方新写场景的中文均在此覆盖）

读档拿不准用哪个 key 时用 detect_key()，写档必须显式传 key。
"""
import struct

KEY_OOZORA = 0xCE
KEY_STEAM_ZHCN = 0x88


def _table(key):
    return bytes(c ^ key for c in range(256))


def parse_lng(raw, key=KEY_OOZORA):
    """Return the list of decoded strings (trailing NUL stripped).

    key 必须与数据源匹配：oozora 补丁用 KEY_OOZORA，Steam 官方中文用
    KEY_STEAM_ZHCN。key 用错时多数条目会直接抛 UnicodeDecodeError，但也可
    能静默解出乱码——拿不准先 detect_key()。
    """
    count = struct.unpack_from('<I', raw, 0)[0]
    lens = struct.unpack_from('<%dH' % count, raw, 4)
    off = 4 + 2 * count
    if off + sum(lens) != len(raw):
        raise ValueError('lng length table does not cover payload')
    tab = _table(key)
    out = []
    for length in lens:
        chunk = raw[off:off + length]
        off += length
        out.append(chunk.translate(tab).decode('utf-16le').rstrip('\0'))
    return out


def detect_key(raw):
    """Guess the XOR key of an lng blob.

    两个候选 key 都解一遍：优先选零解码失败者；都无法区分时（两 key 均
    零失败/均失败）退回 CJK 字符占比更高者。仅用于读入未知来源的 lng，
    写档不要依赖猜测结果。
    """
    def score(key):
        bad = 0
        cjk = 0
        total = 0
        for s in parse_lng_lenient(raw, key):
            total += 1
            cjk += sum(1 for c in s if '\u4e00' <= c <= '\u9fff')
        return bad, cjk / max(total, 1)

    results = {}
    for key in (KEY_STEAM_ZHCN, KEY_OOZORA):
        try:
            results[key] = score(key)
        except Exception:
            results[key] = (10 ** 9, 0.0)
    best = min(results, key=lambda k: (results[k][0], -results[k][1]))
    return best


def parse_lng_lenient(raw, key):
    """parse_lng 但对解码失败的单条字符串用 replace 容错（供检测/统计用）。"""
    count = struct.unpack_from('<I', raw, 0)[0]
    lens = struct.unpack_from('<%dH' % count, raw, 4)
    off = 4 + 2 * count
    if off + sum(lens) != len(raw):
        raise ValueError('lng length table does not cover payload')
    tab = _table(key)
    out = []
    for length in lens:
        chunk = raw[off:off + length]
        off += length
        out.append(chunk.translate(tab).decode('utf-16le', 'replace').rstrip('\0'))
    return out


def encode_lng(strings, key=KEY_OOZORA):
    """Inverse of parse_lng."""
    tab = _table(key)
    blobs = [(s + '\0').encode('utf-16le').translate(tab) for s in strings]
    out = bytearray(struct.pack('<I', len(blobs)))
    for blob in blobs:
        if len(blob) > 0xffff:
            raise ValueError('string exceeds u16 length field')
        out += struct.pack('<H', len(blob))
    for blob in blobs:
        out += blob
    return bytes(out)
