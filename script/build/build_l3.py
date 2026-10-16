# -*- coding: utf-8 -*-
"""L3 画面还原（图形面）：同名图像冲突的扫描、分类、整名覆盖与判定台账。

范围（默认）：`GRAPHIC.arc`、`Chip1.arc`、`CHIP2.arc`。判据见 doc/resource-naming.md §2。

工序（全程只读，除显式开启的写盘）：
  1. 枚举两侧**大小写折叠同名**成员，SHA256 筛出**内容不同**者。候选口径**只认内容哈希**
     ——尺寸差／体积差都不作筛选条件（同尺寸重画会被体积筛漏掉）。
  2. 逐名机械判据：全分辨率逐像素比对 → 同归档原版库缩略图最近邻 →
     放大裁切匹配（取景变化）→ 顶包确认（全分辨率灰度 MAD 达副本级）。
     · 噪声类（大差像素在重编码噪声级、无成形改画区域）        ⇒ keep
     · 其余（同一张画面被改画：叠加遮挡重画／放大裁切）          ⇒ overwrite
     · 顶包（Steam 那张实为原版另一帧副本）**不改变动作**，仍 overwrite
     **决定动作的只有「噪声 vs 非噪声」**；最近邻／放大裁切／顶包只是**证据**。
  3. 对 overwrite 成员**整名覆盖**：成员名与归档表位置不变、内容取原版字节，写
     `asset/<归档>`；**无任何覆盖则不写该归档**（交付面只含有差异者）。
  4. 回读校验：成员数 == backup；被覆盖成员 == 原版同名成员字节；其余成员 == backup 同名字节。
  5. 判定台账落 `resource/censor_map.json`（入库表；消费端 build_restore_plan /
     final_verification 按 `members` 读，故默认沿用其 schema，**按名合并**、保留人工定案字段）。

`.pna` 是图层容器、脚本按 `layer_id` 索引 ⇒ 覆盖前须确认两侧**图层数与层序等价**；
层序不等价者判 keep（不得整名覆盖，否则 Steam 侧既有调用点会越界崩溃）。

实现说明：**纯标准库**（zlib 手写 PNG 解码 + tool/pna.py），不依赖 numpy/Pillow
（本机无网、无第三方包）。为免重复解码，已在台账里的同名条目默认**按名复用其证据**
（`--recompute` 可强制重算）。

用法：
    python script/build/build_l3.py [--archives GRAPHIC.arc,Chip1.arc,CHIP2.arc]
                                    [--orig <原版发行目录>] [--steam backup]
                                    [--asset asset] [--map resource/censor_map.json]
                                    [--emit-map] [--write-asset] [--recompute]
                                    [--schema canonical|nested] [--evidence]

默认 **dry-run**：只扫描、分类、打印结论与拟覆盖名单，不写盘。
`--emit-map` / `--write-asset` 显式开启对应写盘。
"""
import argparse
import hashlib
import json
import os
import re
import struct
import sys
import zlib

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
from tool import paths  # noqa: E402
from tool import pna as pna_mod  # noqa: E402
from tool.arcbuild import HEADER, ENTRY, write_arc, verify  # noqa: E402

DEFAULT_ARCHIVES = ('GRAPHIC.arc', 'Chip1.arc', 'CHIP2.arc')

# ── 判据阈值（与 tmp/scan_image_conflicts.py 同口径）──
BIG_T = 16          # 逐像素「大差」灰度阈值
NOISE_MAX = 32      # 噪声类：全图最大差上限
NOISE_RATIO = 5e-4  # 噪声类：大差像素占比上限
THUMB = (96, 54)    # 最近邻缩略图尺寸
ALIAS_MAD = 1.0     # 顶包：全分辨率灰度 MAD 上限（副本级重合）
ZOOM_LO, ZOOM_HI, ZOOM_STEP = 1.0, 3.0, 0.1

SPI_STD = re.compile(r'^(?P<role>[a-z]+_\d{2})_(?P<diff>\d{2,3})(?P<l>[bs])$', re.I)
SPI_CMP = re.compile(r'^(?P<role>[a-z]+?\d{2})_(?P<diff>\d{2})(?P<l>[bs])$', re.I)
IMG_EXT = ('.png', '.mos', '.jpg', '.bmp')


# ── 归档读表（流式，避免整档载入内存）──
def arc_table(path):
    """返回 {小写名: (磁盘名, 数据绝对偏移, 字节长度)}。"""
    with open(path, 'rb') as f:
        blob = f.read(8)
        if len(blob) < 8:
            raise ValueError('empty archive %s' % path)
        count, table_size = HEADER.unpack(blob)
        table = f.read(table_size)
    data_start = 8 + table_size
    off, out = 0, {}
    for _ in range(count):
        size, rel = ENTRY.unpack_from(table, off)
        off += 8
        start = off
        while table[off:off + 2] != b'\0\0':
            off += 2
        name = table[start:off].decode('utf-16le', 'replace')
        off += 2
        out[name.lower()] = (name, data_start + rel, size)
    return out


def member_sha(path, off, size):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        f.seek(off)
        h.update(f.read(size))
    return h.digest()


def read_member(path, off, size):
    with open(path, 'rb') as f:
        f.seek(off)
        return f.read(size)


def frame_of(fold):
    """帧基名：去扩展名与 B/S 变体后缀（B/S 是同一帧的两个分辨率变体，须成组）。"""
    base = os.path.splitext(fold)[0]
    for rx in (SPI_STD, SPI_CMP):
        m = rx.match(base)
        if m:
            return '%s_%s' % (m.group('role').lower(), m.group('diff'))
    return base.lower()


# ── 纯标准库 PNG 解码（8-bit，colortype 0/2/3/4/6）──
def decode_png(png):
    """→ (w, h, channels, pixels bytes)。colortype 3（调色板）展开为 RGB。"""
    if png[:8] != b'\x89PNG\r\n\x1a\n':
        raise ValueError('not png')
    pos, w, h, bd, ct, idat, plte = 8, None, None, None, None, b'', None
    while pos < len(png):
        ln = struct.unpack_from('>I', png, pos)[0]
        typ = png[pos + 4:pos + 8]
        chunk = png[pos + 8:pos + 8 + ln]
        if typ == b'IHDR':
            w, h, bd, ct = struct.unpack_from('>IIBB', chunk, 0)
        elif typ == b'PLTE':
            plte = chunk
        elif typ == b'IDAT':
            idat += chunk
        elif typ == b'IEND':
            break
        pos += 12 + ln
    if bd != 8:
        raise ValueError('bitdepth %s unsupported' % bd)
    ch = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}[ct]
    raw = zlib.decompress(idat)
    stride = w * ch
    out = bytearray(h * stride)
    prev = bytearray(stride)
    rp = 0
    for y in range(h):
        f = raw[rp]
        rp += 1
        line = bytearray(raw[rp:rp + stride])
        rp += stride
        if f == 1:
            for i in range(ch, stride):
                line[i] = (line[i] + line[i - ch]) & 0xFF
        elif f == 2:
            for i in range(stride):
                line[i] = (line[i] + prev[i]) & 0xFF
        elif f == 3:
            for i in range(stride):
                a = line[i - ch] if i >= ch else 0
                line[i] = (line[i] + (a + prev[i]) // 2) & 0xFF
        elif f == 4:
            for i in range(stride):
                a = line[i - ch] if i >= ch else 0
                b = prev[i]
                c = prev[i - ch] if i >= ch else 0
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                pr = a if (pa <= pb and pa <= pc) else (b if pb <= pc else c)
                line[i] = (line[i] + pr) & 0xFF
        elif f != 0:
            raise ValueError('filter %s' % f)
        out[y * stride:(y + 1) * stride] = line
        prev = line
    if ct == 3:                                  # 调色板 → RGB
        rgb = bytearray(w * h * 3)
        for i, idx in enumerate(out):
            rgb[i * 3:i * 3 + 3] = plte[idx * 3:idx * 3 + 3]
        return w, h, 3, bytes(rgb)
    return w, h, ch, bytes(out)


def to_gray(w, h, ch, pix):
    """转 8-bit 灰度 bytes（长度 w*h）。"""
    if ch == 1:
        return pix
    g = bytearray(w * h)
    if ch == 2:
        for i in range(w * h):
            g[i] = pix[i * 2]
    elif ch == 3:
        for i in range(w * h):
            j = i * 3
            g[i] = (pix[j] * 299 + pix[j + 1] * 587 + pix[j + 2] * 114) // 1000
    else:
        for i in range(w * h):
            j = i * 4
            g[i] = (pix[j] * 299 + pix[j + 1] * 587 + pix[j + 2] * 114) // 1000
    return bytes(g)


def png_gray(data):
    return to_gray(*decode_png(data))


def png_rgb(data):
    w, h, ch, pix = decode_png(data)
    if ch == 3:
        return w, h, pix
    rgb = bytearray(w * h * 3)
    if ch == 1:
        for i in range(w * h):
            v = pix[i]
            rgb[i * 3:i * 3 + 3] = bytes((v, v, v))
    elif ch == 2:
        for i in range(w * h):
            v = pix[i * 2]
            rgb[i * 3:i * 3 + 3] = bytes((v, v, v))
    else:
        for i in range(w * h):
            j = i * 4
            rgb[i * 3:i * 3 + 3] = pix[j:j + 3]
    return w, h, bytes(rgb)


def resize_rgb(w, h, pix, nw, nh):
    """最近邻缩放 RGB bytes。"""
    out = bytearray(nw * nh * 3)
    for y in range(nh):
        sy = min(h - 1, y * h // nh)
        for x in range(nw):
            sx = min(w - 1, x * w // nw)
            si = (sy * w + sx) * 3
            di = (y * nw + x) * 3
            out[di:di + 3] = pix[si:si + 3]
    return bytes(out)


def thumb_rgb(data):
    w, h, pix = png_rgb(data)
    return resize_rgb(w, h, pix, THUMB[0], THUMB[1])


def rgb_mean_abs(a, b):
    n = len(a)
    s = 0
    for i in range(0, n, 3):
        s += abs(a[i] - b[i]) + abs(a[i + 1] - b[i + 1]) + abs(a[i + 2] - b[i + 2])
    return s / (n // 3) / 3.0


def gray_mad(ga, gb):
    if len(ga) != len(gb):
        return None
    return sum(abs(x - y) for x, y in zip(ga, gb)) / len(ga)


def diff_stats_rgb(pa, pb, w, h, big_t=BIG_T):
    """逐像素「大差」统计：d = max(|dr|,|dg|,|db|)（与 tmp/scan_image_conflicts.py 同口径）。"""
    big = 0
    mx = 0
    minx, miny, maxx, maxy = w, h, -1, -1
    step = w * 3
    for y in range(h):
        base = y * step
        for x in range(w):
            j = base + x * 3
            dr = pa[j] - pb[j]
            dg = pa[j + 1] - pb[j + 1]
            db = pa[j + 2] - pb[j + 2]
            d = dr if dr >= 0 else -dr
            t = dg if dg >= 0 else -dg
            if t > d:
                d = t
            t = db if db >= 0 else -db
            if t > d:
                d = t
            if d > mx:
                mx = d
            if d > big_t:
                big += 1
                if x < minx:
                    minx = x
                if x > maxx:
                    maxx = x
                if y < miny:
                    miny = y
                if y > maxy:
                    maxy = y
    bbox = [minx, miny, maxx + 1, maxy + 1] if big else None
    n = w * h
    return {'big_pixels': big, 'big_ratio': round(big / n, 6), 'bbox': bbox, 'max_abs': mx}


# ── PNA 图层比较（覆盖前须确认层数/层序等价）──
def pna_compare(odata, sdata):
    """返回 {'equivalent': bool, 'detail': str}；层数/层序不等价 ⇒ 不得整名覆盖。"""
    try:
        op = pna_mod.load(odata)
        sp = pna_mod.load(sdata)
    except Exception as e:  # noqa: BLE001
        return {'equivalent': False, 'detail': 'parse-error: %r' % e}
    if op['layer_count'] != sp['layer_count']:
        return {'equivalent': False,
                'detail': 'layer_count %d != %d' % (op['layer_count'], sp['layer_count'])}
    o_ids = [e[1] for e in op['entries']]
    s_ids = [e[1] for e in sp['entries']]
    if o_ids != s_ids:
        return {'equivalent': False, 'detail': 'layer_id order differs'}
    # 逐层比子图（尺寸 + 灰度）
    changed = 0
    for i in range(op['layer_count']):
        oi, si = op['images'][i], sp['images'][i]
        if (oi is None) != (si is None):
            changed += 1
            continue
        if oi is None:
            continue
        if oi == si:
            continue
        try:
            if png_gray(oi) != png_gray(si):
                changed += 1
        except Exception:  # noqa: BLE001
            changed += 1
    return {'equivalent': True,
            'detail': 'canvas=%dx%d layers=%d subimage_changed=%d'
                      % (op['canvas_w'], op['canvas_h'], op['layer_count'], changed)}


# ── 扫描 + 分类 ──
def classify_png(odata, sdata, op, o, k, o_thr=None):
    rec = {}
    try:
        ow, oh, oa = png_rgb(odata)
        sw, sh, sb = png_rgb(sdata)
        rec['size_diff'] = (ow, oh) != (sw, sh)
        if rec['size_diff']:
            oa = resize_rgb(ow, oh, oa, sw, sh)
            ow, oh = sw, sh
        rec.update(diff_stats_rgb(oa, sb, sw, sh))
        og, sg = to_gray(sw, sh, 3, oa), to_gray(sw, sh, 3, sb)
        rec['mean_diff'] = round(sum(abs(x - y) for x, y in zip(og, sg)) / len(og), 2)
    except Exception as e:  # noqa: BLE001
        rec['error'] = repr(e)
        rec['class'], rec['action'] = 'keep', 'keep'
        rec['reason'] = '解码失败 ⇒ 不动：%r' % e
        return rec
    noise = rec['max_abs'] <= NOISE_MAX and rec['big_ratio'] <= NOISE_RATIO
    if noise:
        rec['class'], rec['action'] = 'noise', 'keep'
        rec['reason'] = ('重编码噪声：max_abs=%d<=%d 且 big_ratio=%.6f<=%s ⇒ 不动'
                         % (rec['max_abs'], NOISE_MAX, rec['big_ratio'], NOISE_RATIO))
        return rec
    # 非噪声 ⇒ overwrite；下列为证据（最近邻／顶包／放大裁切），失败不影响动作
    rec['class'], rec['action'] = 'censor', 'overwrite'
    rec['reason'] = '改画：非噪声（max_abs=%d, big_ratio=%.6f）⇒ 整名覆盖' % (
        rec['max_abs'], rec['big_ratio'])
    if o_thr:
        try:
            sv = thumb_rgb(sdata)
            best = min(((rgb_mean_abs(v, sv), kk) for kk, v in o_thr.items()), default=None)
            if best:
                rec['nearest'] = {'name': o[best[1]][0], 'distance': round(best[0], 2),
                                  'frame': frame_of(best[1])}
                if rec['nearest']['frame'] != frame_of(k):
                    m = gray_mad(png_gray(read_member(op, o[best[1]][1], o[best[1]][2])), og)
                    if m is not None and m < ALIAS_MAD:
                        rec['alias'] = {'name': o[best[1]][0], 'frame': rec['nearest']['frame'],
                                        'mad': round(m, 2)}
                        rec['class'] = 'reuse'
                        rec['reason'] = ('顶包：Steam 图与原版另一帧 %s 全分辨率 MAD %.2f（副本级）'
                                         '⇒ 整名覆盖' % (rec['alias']['name'], m))
        except Exception:  # noqa: BLE001
            pass
    return rec


def scan_archive(arch, orig_dir, steam_dir, prev_idx, recompute, evidence):
    op = os.path.join(orig_dir, arch)
    sp = os.path.join(steam_dir, arch)
    if not (os.path.exists(op) and os.path.exists(sp)):
        return None
    o, s = arc_table(op), arc_table(sp)
    common = sorted(set(o) & set(s))
    recs = []
    cand = [k for k in common
            if member_sha(op, o[k][1], o[k][2]) != member_sha(sp, s[k][1], s[k][2])]
    # 需要现算的候选（台账里没有、或强制重算）才构建最近邻缩略图库——纯 stdlib 解码
    # 整档很慢，已入库条目直接按名复用证据，避免无谓解码。
    need_compute = [k for k in cand
                    if recompute or (arch, s[k][0].lower()) not in prev_idx]
    o_thr = None
    if evidence and need_compute:
        o_thr = {}
        for k in common:
            if k.endswith('.png'):
                try:
                    o_thr[k] = thumb_rgb(read_member(op, o[k][1], o[k][2]))
                except Exception:  # noqa: BLE001
                    pass
    for k in cand:
        oname, ooff, osz = o[k]
        sname, soff, ssz = s[k]
        old = prev_idx.get((arch, sname.lower()))
        if old and not recompute:
            rec = dict(old)
            rec['fold'] = k
            rec['reason'] = old.get('reason') or ('台账既有条目（class=%s）⇒ 沿用' % old.get('class'))
            rec['from_map'] = True
            recs.append(rec)
            continue
        rec = {'archive': arch, 'name': sname, 'orig_name': oname, 'fold': k,
               'ext': os.path.splitext(k)[1], 'dims': {'orig_size': osz, 'steam_size': ssz}}
        odata = read_member(op, ooff, osz)
        sdata = read_member(sp, soff, ssz)
        if k.endswith('.pna'):
            pc = pna_compare(odata, sdata)
            rec['pna'] = pc
            if pc['equivalent']:
                rec['class'], rec['action'] = 'censor', 'overwrite'
                rec['reason'] = 'pna 层序等价、内容改画 ⇒ 整名覆盖（%s）' % pc['detail']
            else:
                rec['class'], rec['action'] = 'keep', 'keep'
                rec['reason'] = 'pna 层数/层序不等价 ⇒ 不动（%s）' % pc['detail']
        elif rec['ext'] in IMG_EXT:
            rec['frame'] = frame_of(k)
            rec.update(classify_png(odata, sdata, op, o, k, o_thr))
        else:
            rec['class'], rec['action'] = 'keep', 'keep'
            rec['reason'] = '非图像成员，不进画面覆盖面'
        recs.append(rec)
    return {'archive': arch, 'orig_count': len(o), 'steam_count': len(s),
            'common': len(common), 'cand': len(cand), 'recs': recs}


# ── 整名覆盖写盘 ──
def apply_overwrites(arch, orig_dir, steam_dir, asset_dir, ow_names):
    """把归档里 ow_names（小写）成员字节换成原版同名成员字节，写 asset/<归档>。

    以 **asset 现有文件为底**（保留其它工序已并入的成员，如 L4 补入），否则以 backup 为底；
    成员名与表位置不变，只换内容 ⇒ 与 build_patch.py 的覆盖语义一致。
    """
    out = os.path.join(asset_dir, arch)
    base = out if os.path.exists(out) else os.path.join(steam_dir, arch)
    with open(base, 'rb') as f:
        blob = f.read()
    count, table_size = HEADER.unpack_from(blob, 0)
    data_start = 8 + table_size
    members, off = [], 8
    for _ in range(count):
        size, rel = ENTRY.unpack_from(blob, off)
        off += 8
        start = off
        while blob[off:off + 2] != b'\0\0':
            off += 2
        members.append([blob[start:off],
                        bytearray(blob[data_start + rel:data_start + rel + size])])
        off += 2
    o = arc_table(os.path.join(orig_dir, arch))
    replaced = 0
    for m in members:
        low = m[0].decode('utf-16le', 'replace').lower()
        if low in ow_names:
            oname, ooff, osz = o[low]
            with open(os.path.join(orig_dir, arch), 'rb') as f:
                f.seek(ooff)
                m[1] = bytearray(f.read(osz))
            replaced += 1
    assert replaced == len(ow_names), '%s: 覆盖数 %d != 名单 %d' % (arch, replaced, len(ow_names))
    write_arc([(bytes(nb), bytes(d)) for nb, d in members], out)
    verify(out, expect_count=len(members))
    return out, replaced


def readback_check(arch, orig_dir, steam_dir, asset_dir, ow_names):
    """回读产物：① 成员数 == backup；② 被覆盖成员 == 原版字节；③ 其余成员 == backup 字节。"""
    out = os.path.join(asset_dir, arch)
    a, s = arc_table(out), arc_table(os.path.join(steam_dir, arch))
    o = arc_table(os.path.join(orig_dir, arch))
    assert len(a) == len(s), '%s: 成员数 %d != backup %d' % (arch, len(a), len(s))
    for low, (sname, soff, ssz) in s.items():
        if low not in a:
            raise AssertionError('%s: 产物缺 backup 成员 %s' % (arch, sname))
        an, aoff, asz = a[low]
        if low in ow_names:
            if member_sha(out, aoff, asz) != member_sha(os.path.join(orig_dir, arch),
                                                        o[low][1], o[low][2]):
                raise AssertionError('%s: 覆盖成员 %s != 原版字节' % (arch, sname))
        elif member_sha(out, aoff, asz) != member_sha(os.path.join(steam_dir, arch), soff, ssz):
            raise AssertionError('%s: 非覆盖成员 %s != backup 字节' % (arch, sname))
    return len(a), len(ow_names)


# ── 判定台账 ──
def emit_map(records, map_path, schema, archives=None):
    """写判定台账。canonical = 沿用现有 members/meta/series（按名合并、保留人工字段）；
    nested = 任务描述里的 {归档: {成员: {action, reason, evidence}}}。"""
    if schema == 'nested':
        doc = {a: {} for a in (archives or [])}
        for r in records:
            doc.setdefault(r['archive'], {})[r['name']] = {
                'action': r['action'], 'reason': r.get('reason', ''),
                'evidence': {k: r.get(k) for k in
                             ('class', 'frame', 'size_diff', 'big_pixels', 'big_ratio',
                              'bbox', 'mean_diff', 'max_abs', 'nearest', 'alias', 'pna')
                             if r.get(k) is not None},
            }
        with open(map_path, 'w', encoding='utf-8', newline='\n') as f:
            json.dump(doc, f, ensure_ascii=False, indent=1, sort_keys=True)
            f.write('\n')
        return len(records)

    prev = {}
    if os.path.exists(map_path):
        with open(map_path, encoding='utf-8') as f:
            prev = json.load(f)
    idx = {(m['archive'], m['name'].lower()): m for m in prev.get('members', [])}
    series = dict(prev.get('series', {}))
    for r in records:
        key = (r['archive'], r['name'].lower())
        old = idx.get(key, {})
        frame = r.get('frame') or old.get('frame')
        entry = dict(old)
        entry.update({
            'archive': r['archive'], 'name': r['name'], 'orig_name': r['orig_name'],
            'class': r['class'], 'action': r['action'], 'frame': frame,
            'dims': r.get('dims', old.get('dims')),
            'size_diff': r.get('size_diff', old.get('size_diff')),
            'big_pixels': r.get('big_pixels', old.get('big_pixels')),
            'big_ratio': r.get('big_ratio', old.get('big_ratio')),
            'bbox': r.get('bbox', old.get('bbox')),
            'mean_diff': r.get('mean_diff', old.get('mean_diff')),
            'max_abs': r.get('max_abs', old.get('max_abs')),
            'nearest': r.get('nearest', old.get('nearest')),
            'zoom': r.get('zoom', old.get('zoom')),
            'alias': r.get('alias', old.get('alias')),
            'pna': r.get('pna', old.get('pna')),
            'reason': r.get('reason', old.get('reason')),
            'series': old.get('series') or '%s/%s' % (
                r['archive'], '_'.join((frame or r['fold']).split('_')[:2])),
            'review': old.get('review', 'machine'),
        })
        idx[key] = entry
        series.setdefault(entry['series'], {'class': r['class']})
    members = [idx[k] for k in sorted(idx)]
    doc = {'members': members, 'series': {k: series[k] for k in sorted(series)},
           'meta': dict(prev.get('meta', {}),
                        archives=sorted({m['archive'] for m in members}))}
    with open(map_path, 'w', encoding='utf-8', newline='\n') as f:
        json.dump(doc, f, ensure_ascii=False, indent=1, sort_keys=True)
        f.write('\n')
    return len(records)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--archives', default=','.join(DEFAULT_ARCHIVES))
    ap.add_argument('--orig', default=None)
    ap.add_argument('--steam', default=paths.STEAM)
    ap.add_argument('--asset', default=os.path.join(ROOT, 'asset'))
    ap.add_argument('--map', default=os.path.join(ROOT, 'resource', 'censor_map.json'))
    ap.add_argument('--prev-map', default=None,
                    help='既有台账（默认取 --map）；用于按名复用证据，可与 --map 不同路径')
    ap.add_argument('--emit-map', action='store_true', help='写判定台账（默认 dry-run）')
    ap.add_argument('--write-asset', action='store_true', help='写 asset/<归档>（默认 dry-run）')
    ap.add_argument('--recompute', action='store_true', help='忽略台账既有条目、强制重算证据')
    ap.add_argument('--no-evidence', dest='evidence', action='store_false',
                    help='跳过最近邻/顶包证据（更快）')
    ap.add_argument('--schema', choices=('canonical', 'nested'), default='canonical')
    a = ap.parse_args()

    orig_dir = a.orig or paths.orig_dir()
    archives = [x.strip() for x in a.archives.split(',') if x.strip()]
    prev_path = a.prev_map or a.map
    prev_idx = {}
    if os.path.exists(prev_path):
        with open(prev_path, encoding='utf-8') as f:
            for m in json.load(f).get('members', []):
                prev_idx[(m['archive'], m['name'].lower())] = m
    all_recs, lines = [], []
    for arch in archives:
        res = scan_archive(arch, orig_dir, a.steam, prev_idx, a.recompute, a.evidence)
        if res is None:
            lines.append('%-14s MISSING-ON-ONE-SIDE' % arch)
            continue
        ow = [r for r in res['recs'] if r['action'] == 'overwrite']
        kp = [r for r in res['recs'] if r['action'] == 'keep']
        lines.append('%-14s orig=%-4d steam=%-4d common=%-4d content_diff=%-3d '
                     'overwrite=%-3d keep=%-3d'
                     % (arch, res['orig_count'], res['steam_count'], res['common'],
                        res['cand'], len(ow), len(kp)))
        for r in res['recs']:
            tag = ' [map]' if r.get('from_map') else ''
            lines.append('    %-24s %-9s %-9s %s%s'
                         % (r['name'], r['action'], r.get('class'), r.get('reason', ''), tag))
        all_recs.extend(res['recs'])

    report = '\n'.join(lines)
    print(report)
    if not all_recs:
        print('\n无同名内容差 ⇒ 无覆盖、不写 asset/')
    wrote = False
    for arch in archives:
        recs = [r for r in all_recs if r['archive'] == arch and r['action'] == 'overwrite']
        if not recs:
            continue
        names = {r['fold'] for r in recs}
        if a.write_asset:
            out, n = apply_overwrites(arch, orig_dir, a.steam, a.asset, names)
            cnt, n2 = readback_check(arch, orig_dir, a.steam, a.asset, names)
            print('WROTE %s: %d 覆盖，回读校验通过（成员 %d）' % (out, n, cnt))
            wrote = True
        else:
            print('[dry-run] %s: 拟整名覆盖 %d 名' % (arch, len(names)))
    if a.emit_map and (all_recs or a.schema == 'nested'):
        n = emit_map(all_recs, a.map, a.schema, archives)
        print('MAP %s: 合并 %d 条（schema=%s）' % (a.map, n, a.schema))
    elif a.emit_map:
        print('MAP 跳过：无同名内容差条目（canonical 表无须改动）')
    os.makedirs(os.path.join(ROOT, 'tmp'), exist_ok=True)
    with open(os.path.join(ROOT, 'tmp', 'build_l3_report.txt'), 'w',
              encoding='utf-8', newline='\n') as f:
        f.write(report + '\n')
    print('\nreport -> tmp/build_l3_report.txt (wrote_asset=%s)' % wrote)


if __name__ == '__main__':
    main()
