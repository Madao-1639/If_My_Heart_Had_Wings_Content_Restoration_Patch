# -*- coding: utf-8 -*-
"""还原内容的 文本-语音-CG 一致性校验（只读，两路对账）。

路 A（计划图）：承载图 1:1 块里，原版行与 Steam 槽各自带的语音号／画面名对不上
  ⇒ 该块的「逐行互译」是**假配对**（判据见 doc/resource-naming.md §2 红线），据此做出的
  改绑／顶包结论都不可靠。每条发现都带**两侧原句**与 Steam 侧文本形状（拉丁改写行＝该行
  被 Steam 重写）；命中且计划按 1:1 承载（原版行从未进产物）⇒ 归**还原缺口**，不是渲染错位。
路 B（pipeline 操作）：在产物 `asset/Rio.arc` 上逐槽实测 (文本, 语音, 画面) 三元组，与
  `resource/restore_plan.json` 声明的**来源**比对（保留格＝Steam 自己、插入格＝原版行），
  再核该槽引用的资源在产物归档里解析到的**就是原版内容**。

归属口径与承载图／判读批次一致：token 归**其后最近一条 `14`**；本槽没带则沿用前一格
（语音与画面都是延续语义）。写盘器只删被删行的 `14`＋名字框 ⇒ 被删行的 token 会落进
后继格的归属区，这类点单独分成 residue 级，不与真错位混为一谈。

用法：
    python script/verify_sync.py --orig-dir <原版目录> [--asset asset] [--scripts A,B]
                                 [--max-rows 400] [--out tmp/verify_sync.md]

退出码：0 = 无 HARD 级发现；1 = 有 HARD 级发现；2 = 输入缺失／前置不成立。
控制台只输出 ASCII，日文/中文一律写进报告文件（AGENTS.md §工程约定 4）。
"""
import argparse
import bisect
import collections
import hashlib
import json
import os
import re
import struct
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from tool import arcbuild, lng, scriptext, ws2, ws2dis  # noqa: E402
from tool import fancn  # noqa: E402
from tool.ws2conv import load_orig_formats, parse as conv_parse  # noqa: E402

RESOURCE_ARCHIVES = ['VOICE.arc', 'Chip1.arc', 'CHIP2.arc', 'CHIP3.arc', 'CHIP4.arc',
                     'CHIP5.arc', 'CHIP6.arc', 'GRAPHIC.arc', 'SE.arc', 'BGM.arc']
KIND_ARCH = {'voice': 'VOICE.arc', 'se': 'SE.arc', 'bgm': 'BGM.arc'}
HARD, REVIEW = 'HARD', 'REVIEW'
LATIN = re.compile(r'[A-Za-z]')

# 已知良性 CG 名差异（背景 / scenery，非角色 / 事件 CG，亦非被删改的露骨内容）。
# 原版与该 Steam 槽的 CG 调用点名不同，但属同一场景的不同背景渲染或原版自身行为，
# 不在「内容还原」范围内（范围＝H 场景内容 + 出入口 + L3 台词）。逐项已逐字节 / 逐像素核对为
# 不同图，确认非「同图异名」误报；其中 KOT_003 那条由顶包存活格改写（KOT_12_007s→KOT_12_002B）
# 覆盖，属原版行为（见 doc/restoration-targets.md 关联讨论）。
# 含 carried-1to1（未还原、已逐图核对为良性背景差）与 re-inserted（已 rebind 还原、标志仅为承载图
# 残留记录）两类 —— 二者皆为误报。
KNOWN_BENIGN_CG_DIFF = {
    # carried-1to1（已逐图核对：不同背景渲染，out of scope）
    ('AMA_010', 'BG05E_01B.PNG', 'BG05C_01B.PNG'),   # 不同背景渲染（2560×1440，RGB vs RGBA，99.5% 像素不同）
    ('KOT_003', 'KOT_12_002B.PNG', 'KOT_12_007S.PNG'),  # 原版行为：顶包改写 KOT_12_007s→KOT_12_002B 已覆盖
    ('YOR_004', 'BG00_01S.PNG', 'SKY01_01B.PNG'),    # 不同背景（1280×720 vs 2560×1440）
    # re-inserted（已 rebind 还原，标志仅为承载图残留记录）
    ('AGE_005', 'BG00_01S.PNG', 'AGE_06_008B.PNG'),
    ('AGE_007', 'BG00_01S.PNG', 'AGE_10_001S.PNG'),
    ('AGE_010', 'BG00_01S.PNG', 'BG20_01B.PNG'),
}

# 已知的良性顶包改写点（原版行为）：判读表 `slot` 记的是「显示指令之前那一行」，而产物里改写
# 落在其后一条 14 的前奏里，两者差一格属承载图归属口径，非缺陷。用户已确认 KOT_12_007s→
# KOT_12_002B 是原版行为，不应报错（见 doc/restoration-targets.md 关联讨论）。
KNOWN_BENIGN_REUSE_SLOT_FIELD = {
    ('KOT_003', 'KOT_12_007S.PNG', 'KOT_12_002B.PNG'),
}
CJK = re.compile(r'[\u3040-\u30ff\u31f0-\u31ff\u4e00-\u9fff]')


def s(b):
    """bytes → 可读串（只进报告，不进控制台）。"""
    if b is None:
        return None
    return b.decode('cp932', 'replace') if isinstance(b, bytes) else b


# ──────────────────────────────── 归档 ────────────────────────────────

def arc_table(path):
    """成员表（不读数据区）→ {小写名: 磁盘原名}。"""
    with open(path, 'rb') as f:
        count, table_size = struct.unpack('<II', f.read(8))
        tbl = f.read(table_size)
    out, p = {}, 0
    for _ in range(count):
        p += 8
        q = p
        while tbl[q:q + 2] != b'\x00\x00':
            q += 2
        name = tbl[p:q].decode('utf-16le', 'replace')
        p = q + 2
        out.setdefault(name.lower(), name)
    return out


def arc_hashes(path, low_names):
    """按需 seek 读成员字节 → {小写名: sha256}。"""
    want = set(low_names)
    out = {}
    if not want:
        return out
    with open(path, 'rb') as f:
        count, table_size = struct.unpack('<II', f.read(8))
        tbl = f.read(table_size)
        data_start = 8 + table_size
        p = 0
        for _ in range(count):
            size, rel = struct.unpack_from('<II', tbl, p)
            p += 8
            q = p
            while tbl[q:q + 2] != b'\x00\x00':
                q += 2
            low = tbl[p:q].decode('utf-16le', 'replace').lower()
            p = q + 2
            if low in want and low not in out:
                f.seek(data_start + rel)
                out[low] = hashlib.sha256(f.read(size)).hexdigest()
    return out


def rio_members(arc_path):
    out = {}
    for nb, d in arcbuild.read_raw(arc_path):
        n = nb.decode('utf-16le', 'replace')
        if n.lower().endswith('.ws2'):
            out[n[:-4].upper()] = d
    return out


def lng_texts(raw, key):
    """逐条解出 .lng 文本，容忍表尾多余字节。

    官方 zh-CN 归档内 CO1_003.lng / CO2_002.lng 尾部带多余填充，`lng.parse_lng`
    的严格长度校验会直接抛错；这里按 count + 长度表逐条读取，忽略尾部填充。
    """
    count = struct.unpack_from('<I', raw, 0)[0]
    lens = struct.unpack_from('<%dH' % count, raw, 4)
    off = 4 + 2 * count
    tab = bytes(c ^ key for c in range(256))
    out = []
    for length in lens:
        chunk = raw[off:off + length]
        if len(chunk) != length:
            raise ValueError('lng payload truncated')
        off += length
        out.append(chunk.translate(tab).decode('utf-16le').rstrip('\0'))
    return out


def lng_members(arc_path, key):
    out = {}
    for nb, d in arcbuild.read_raw(arc_path):
        n = nb.decode('utf-16le', 'replace')
        if n.lower().endswith('.lng'):
            out[n[:-4].upper()] = lng_texts(d, key)
    return out


# ──────────────────────────────── 槽与 token ────────────────────────────────

def instructions(dec, ofmt=None):
    """解码流 → [(偏移, op, 操作数)]。`ofmt` 给了就按原版格式表线性解析。"""
    if ofmt is None:
        instrs, ok = ws2dis.disassemble(dec)
        assert ok, 'steam-table parse desynced'
        return [(off, op, ops) for off, op, _sz, ops in instrs]
    parsed, _tail = conv_parse(dec, ofmt)
    out, p = [], 0
    for op, ops in parsed:
        out.append((p, op, ops))
        p += 1 + len(ops)
    return out


def token_of(op, ops):
    """显示／配音指令 → (kind, 通道, 名字大写 bytes)；非相关指令 None。"""
    if op not in (0x1E, 0x28, 0x33, 0x34):
        return None
    parts = ops.split(b'\x00')
    if len(parts) < 2 or not parts[1]:
        return None
    chan, name = parts[0], parts[1].upper()
    if op == 0x28:
        kind = 'voice' if chan.upper().startswith(b'CHAR') else 'se'
    elif op == 0x1E:
        kind = 'bgm'
    elif op == 0x33:
        kind = 'cg'
    else:
        kind = 'sprite'
    return kind, chan, name


def scan_cells(dec, ofmt=None):
    """逐 `14` 槽 → {'off','id','tok'(本格直接携带),'own'(末值),'eff'(含延续)}。"""
    cells, pend = [], []
    for off, op, ops in instructions(dec, ofmt):
        if op == 0x14:
            cells.append({'off': off, 'id': struct.unpack_from('<H', ops, 0)[0], 'tok': pend})
            pend = []
        elif op != 0x15:
            t = token_of(op, ops)
            if t:
                pend.append(t)
    for i, c in enumerate(cells):
        own = {}
        sp = {}
        for kind, chan, nm in c['tok']:
            if kind == 'sprite':
                sp[chan.upper()] = nm
            elif kind == 'se':
                own.setdefault('se', []).append(nm)
            else:
                own[kind] = nm
        if sp:
            own['sprite'] = sp
        eff = dict(own)
        eff['se'] = list(own.get('se', []))
        if i:
            prev = cells[i - 1]['eff']
            for k in ('voice', 'cg', 'bgm'):
                if k not in eff and k in prev:
                    eff[k] = prev[k]
            ecr = dict(prev.get('sprite', {}))
            ecr.update(own.get('sprite', {}))
            if ecr:
                eff['sprite'] = ecr
        c['own'] = own
        c['eff'] = eff
    return cells


def dlg_rows(name, raw):
    """承载图口径的 dlg/ctrl 行（含行内文本，序与 row_tokens 一致）。"""
    return [r for r in scriptext.script_rows(name, raw) if r['kind'] in ('dlg', 'ctrl')]


def n_rows(name, raw):
    """承载图口径的 dlg/ctrl 行数。"""
    return len(dlg_rows(name, raw))


def row_tokens(dec, ofmt=None):
    """dlg/ctrl 行序 → 该行直接携带的 voice/cg（与承载图同一口径、同一归属规则）。"""
    offs = [r['off'] for r in scriptext.script_rows('X', ws2.encode(dec))
            if r['kind'] in ('dlg', 'ctrl')]
    toks = []
    for off, op, ops in instructions(dec, ofmt):
        t = token_of(op, ops)
        if t and t[0] in ('voice', 'cg'):
            toks.append((off, t[0], t[2]))
    out = [{} for _ in offs]
    for x, kind, nm in toks:
        k = bisect.bisect_right(offs, x)
        if k < len(offs):
            out[k].setdefault(kind, nm)
    return out


# ──────────────────────────────── 计划的槽序 ────────────────────────────────

def expected_sequence(host, n_steam_cells):
    """复现 `tool/writer.rebuild_host` 的 `14` 槽序 + 标出块尾前奏的落点。

    返回 (seq, tail)：
      seq[j]  = 产物第 j 格的来源 ('steam', k) | ('orig', r)
      tail[j] = 恒为空。写盘器的块跨度＝`[o14[r0-1]+1, o14[r1]+1)`，即行 r0..r1 各自的
                演出前缀＋正文；**不携带 r1+1 的演出前缀**（携带会让同一触发连发两次
                ⇒ 产物出现「同格重复语音」，见 doc/lessons-learned.md §16）。
    锚点落在被删格上（rebind 改绑）时，插入块就位于该格原本的位置。
    """
    plan = host['plan']
    drops = set(plan['drops'])
    by_anchor = collections.defaultdict(list)
    for a, r0, r1 in plan['inserts']:
        by_anchor[a].append((r0, r1))

    seq, tail = [], {}
    pending = [None]

    def emit(item):
        seq.append(item)
        if pending[0] is not None:
            tail[len(seq) - 1] = pending[0]
            pending[0] = None

    def run(r0, r1):
        for r in range(r0, r1 + 1):
            emit(('orig', r))
        # 写盘器的块跨度右端收到 r1 的 `14` 之后即止，**不携带 r1+1 的演出前缀**
        # ⇒ 无「块尾前奏」，`tail` 恒为空（见 doc/lessons-learned.md §16）
        pending[0] = None

    for r0, r1 in sorted(by_anchor.get(-1, [])):
        run(r0, r1)
    for k in range(n_steam_cells):
        if k not in drops:
            emit(('steam', k))
        for r0, r1 in sorted(by_anchor.get(k, [])):
            run(r0, r1)
    return seq, tail


def merge_own(a, b):
    """合并两段的直接携带值，b 在后（流内末值口径）。"""
    out = dict(a)
    for k, v in b.items():
        if k == 'sprite':
            d = dict(out.get('sprite', {}))
            d.update(v)
            out['sprite'] = d
        elif k == 'se':
            out['se'] = list(out.get('se', [])) + list(v)
        else:
            out[k] = v
    return out


def eff_chain(owns):
    """逐格直接值 → 逐格「本行在屏／在播」值（延续语义）。"""
    effs, prev = [], {}
    for own in owns:
        e = dict(own)
        e['se'] = list(own.get('se', []))
        for k in ('voice', 'cg', 'bgm'):
            if k not in e and k in prev:
                e[k] = prev[k]
        lay = dict(prev.get('sprite', {}))
        lay.update(own.get('sprite', {}))
        if lay:
            e['sprite'] = lay
        prev = e
        effs.append(e)
    return effs


def refs_of(cell):
    """本格直接引用的资源 → [(kind, name bytes, 指定归档或 None)]。"""
    out = []
    own = cell['own']
    for k in ('voice', 'cg', 'bgm'):
        if k in own:
            out.append((k, own[k], KIND_ARCH.get(k)))
    for nm in own.get('se', []):
        out.append(('se', nm, 'SE.arc'))
    for nm in own.get('sprite', {}).values():
        out.append(('img', nm, None))
    return out


# ──────────────────────────────── 主流程 ────────────────────────────────

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--orig-dir', default=os.environ.get('IFMH_ORIG_DIR', ''))
    ap.add_argument('--asset', default=os.path.join(ROOT, 'asset'))
    ap.add_argument('--backup', default=os.path.join(ROOT, 'backup'))
    ap.add_argument('--scripts', default='')
    ap.add_argument('--out', default=os.path.join(ROOT, 'tmp', 'verify_sync.md'))
    ap.add_argument('--max-rows', type=int, default=400)
    args = ap.parse_args()

    if not args.orig_dir or not os.path.isdir(args.orig_dir):
        sys.stderr.write('need --orig-dir (or IFMH_ORIG_DIR)\n')
        return 2
    if not os.path.isdir(args.asset):
        sys.stderr.write('no product tree at %s\n' % args.asset)
        return 2

    plan = json.load(open(os.path.join(ROOT, 'resource', 'restore_plan.json'), encoding='utf-8'))
    carrier = json.load(open(os.path.join(ROOT, 'resource', 'carrier_map.json'), encoding='utf-8'))
    ofmt = load_orig_formats(args.orig_dir)

    steam_raw = rio_members(os.path.join(args.backup, 'Rio.arc'))
    orig_raw = rio_members(os.path.join(args.orig_dir, 'Rio.arc'))
    prod_raw = rio_members(os.path.join(args.asset, 'Rio.arc'))
    zh_off = lng_members(os.path.join(args.backup, 'zh-CN', 'Rio.arc'), lng.KEY_STEAM_ZHCN)
    zh_prod = lng_members(os.path.join(args.asset, 'zh-CN', 'Rio.arc'), lng.KEY_STEAM_ZHCN)

    steam_tab, prod_tab, orig_tab, delivered = {}, {}, {}, {}
    for arch in RESOURCE_ARCHIVES:
        pb, pa, po = (os.path.join(args.backup, arch), os.path.join(args.asset, arch),
                      os.path.join(args.orig_dir, arch))
        steam_tab[arch] = arc_table(pb) if os.path.exists(pb) else {}
        prod_tab[arch] = arc_table(pa) if os.path.exists(pa) else {}
        orig_tab[arch] = arc_table(po) if os.path.exists(po) else {}
        delivered[arch] = pa if os.path.exists(pa) else pb
    orig_where = {}
    for arch in RESOURCE_ARCHIVES:
        for low in orig_tab[arch]:
            orig_where.setdefault(low, arch)
    steam_where = {}
    for arch in RESOURCE_ARCHIVES:
        for low in steam_tab[arch]:
            steam_where.setdefault(low, arch)

    ow_roster = {(e['archive'].lower(), e['name'].lower()) for e in plan['resources']['overwrite']}
    copy_roster = {e['orig'].lower() for e in plan['resources']['copy']}
    # 判定表里显式判为「噪声/不动」的成员：产物字节＝Steam 字节属决策，不算未覆盖
    keep_roster = set()
    for _fn in ('censor_map.json', 'voice_conflict_map.json'):
        _p = os.path.join(ROOT, 'resource', _fn)
        if os.path.exists(_p):
            for _m in json.load(open(_p, encoding='utf-8'))['members']:
                if _m.get('action') == 'keep':
                    keep_roster.add((_m['archive'].lower(), _m['name'].lower()))

    finds = []

    def add(level, group, script, **kw):
        finds.append((level, group, script, kw))

    scope = sorted(list(plan['A1']) + [s0 for s0, h in plan['hosts'].items() if h['kind'] == 'host'])
    if args.scripts:
        want = {x.strip().upper() for x in args.scripts.split(',') if x.strip()}
        scope = [x for x in scope if x in want]

    A = collections.Counter()
    B = collections.Counter()
    R = collections.Counter()

    # ── 路 A：承载图 1:1 块的语音／画面归属（只在有改动的脚本上做）──
    def disposition(script, row, slot):
        """这一对在计划里**实际被怎么用**（决定错配是否构成缺口）。"""
        if script in plan['A1']:
            return 'whole-script'
        host = plan['hosts'].get(script)
        if not host or host.get('kind') != 'host':
            return 'no-host'
        p = host['plan']
        if any(r0 <= row <= r1 for _a, r0, r1 in p['inserts']):
            return 're-inserted'
        if slot in set(p['drops']):
            return 'slot-dropped'
        return 'carried-1to1'

    def text_shape(t):
        """'latin'＝Steam 改写行（有拉丁字母、无假名／汉字）；否则 'cjk'；空文本 'none'。"""
        if not t:
            return 'none'
        return 'latin' if LATIN.search(t) and not CJK.search(t) else 'cjk'

    def pair_evidence(tx_o, tx_s, r, k):
        """这一对两侧的原句（供目视核对，判断是真改写还是同句改画）。"""
        to = tx_o[r] if r < len(tx_o) else None
        ts = tx_s[k] if k < len(tx_s) else None
        return {'orig_text': to[:60] if to else None,
                'steam_text': ts[:60] if ts else None,
                'steam_text_kind': text_shape(ts)}

    for script in scope:
        if script not in carrier:
            continue
        s_raw, o_raw = steam_raw.get(script), orig_raw.get(script)
        if not s_raw or not o_raw:
            add(HARD, 'A0-no-source', script, steam=bool(s_raw), orig=bool(o_raw))
            continue
        # 匹配行文本覆盖口径（2026-10-07）：计划声明这些 steam 槽的 zh 用原版行民汉；
        # 覆盖槽上的语音/画面分歧属声明内已知偏差（见 A1 发射处的降级）
        _hp = plan['hosts'].get(script, {})
        text_overrides = {int(k): v for k, v in
                          (_hp.get('plan', {}).get('text_overrides') or {}).items()}
        rt_o = row_tokens(ws2.decode(o_raw), ofmt)
        rt_s = row_tokens(ws2.decode(s_raw))
        tx_o = [r['jp'] for r in dlg_rows(script, o_raw)]
        tx_s = [r['jp'] for r in dlg_rows(script, s_raw)]
        for b in carrier[script]['blocks']:
            if b['kind'] not in ('anchor', 'match'):
                continue
            o_r, s_r = b.get('orig'), b.get('steam')
            if not o_r or not s_r:
                continue
            for r in range(o_r[0], o_r[1] + 1):
                k = s_r[0] + (r - o_r[0])
                if k > s_r[1] or r >= len(rt_o) or k >= len(rt_s):
                    A['pair_oob'] += 1
                    continue
                A['pairs'] += 1
                ov, sv = rt_o[r].get('voice'), rt_s[k].get('voice')
                oc, sc_ = rt_o[r].get('cg'), rt_s[k].get('cg')
                if ov and sv:
                    if ov == sv:
                        A['voice_equal'] += 1
                        continue
                    A['voice_diff'] += 1
                    dp = disposition(script, r, k)
                    known = sv.lower() in orig_tab['VOICE.arc']
                    carried = dp == 'carried-1to1'
                    if carried:
                        A['voice_diff_carried'] += 1
                        if text_shape(tx_s[k] if k < len(tx_s) else None) == 'latin':
                            A['voice_diff_carried_latin'] += 1
                    else:
                        A['voice_diff_other'] += 1
                    # 覆盖槽＝该对已被等长复审判定且按 2026-10-07 口径只做文本覆盖，
                    # 语音/画面留 Steam 侧是**声明内的已知偏差**，不是未处理缺陷
                    overridden = k in text_overrides
                    add(REVIEW if overridden else (HARD if carried else REVIEW),
                        'A1-fake-1to1-voice', script, row=r, slot=k,
                        orig_voice=s(ov), steam_voice=s(sv),
                        steam_voice_in_orig_archive=known,
                        disposition=('text-overridden' if overridden else dp),
                        **pair_evidence(tx_o, tx_s, r, k))
                elif ov or sv:
                    A['voice_one_side'] += 1
                    add(REVIEW, 'A1-voice-one-side', script, row=r, slot=k,
                        orig_voice=s(ov), steam_voice=s(sv),
                        disposition=disposition(script, r, k),
                        **pair_evidence(tx_o, tx_s, r, k))
                if oc and sc_ and oc != sc_:
                    A['cg_diff'] += 1
                    if (script, s(oc).upper(), s(sc_).upper()) in KNOWN_BENIGN_CG_DIFF:
                        A['cg_diff_benign_whitelisted'] += 1
                        continue
                    add(REVIEW, 'A2-fake-1to1-cg', script, row=r, slot=k,
                        orig_cg=s(oc), steam_cg=s(sc_),
                        disposition=disposition(script, r, k),
                        **pair_evidence(tx_o, tx_s, r, k))

    # ── 路 B：产物逐槽三元组 ──
    need_hash = set()
    for script in scope:
        whole = script in plan['A1']
        s_raw, o_raw, p_raw = steam_raw.get(script), orig_raw.get(script), prod_raw.get(script)
        if p_raw is None:
            add(HARD, 'B0-absent-in-product', script)
            continue
        if o_raw is None:
            add(HARD, 'B0-absent-in-orig', script)
            continue
        p_cells = scan_cells(ws2.decode(p_raw))
        o_cells = scan_cells(ws2.decode(o_raw), ofmt)
        s_cells = scan_cells(ws2.decode(s_raw)) if s_raw else []

        # G1 槽序口径必须一致：计划按 dlg/ctrl 行，写盘器按解析出的 14
        if s_raw:
            if len(s_cells) != n_rows(script, s_raw):
                add(HARD, 'G1-steam-slot-caliber', script, parsed_14=len(s_cells),
                    dlg_ctrl_rows=n_rows(script, s_raw))
        if len(o_cells) != n_rows(script, o_raw):
            add(HARD, 'G1-orig-slot-caliber', script, parsed_14=len(o_cells),
                dlg_ctrl_rows=n_rows(script, o_raw))
        o_ids = [c['id'] for c in o_cells]
        if o_ids and o_ids != list(range(len(o_ids))):
            bad = next(i for i, v in enumerate(o_ids) if v != i)
            add(HARD, 'G2-orig-id-not-sequential', script, first_bad_row=bad,
                id_at_that_row=o_ids[bad], n_rows=len(o_ids))

        if whole:
            exp = [('orig', r) for r in range(len(o_cells))]
            tail = {}
            drops = set()
            text_overrides = {}
        else:
            host = plan['hosts'][script]
            exp, tail = expected_sequence(host, len(s_cells))
            drops = set(host['plan']['drops'])
            # 覆盖口径（2026-10-07）在**本循环**再取一次：上面的定义属路 A 循环，
            # 到这里已是上一脚本的残留值
            text_overrides = {int(k): v for k, v in
                              (host['plan'].get('text_overrides') or {}).items()}
        fan = fancn.load_texts(script)
        off_lng = zh_off.get(script, [])
        prod_lng = zh_prod.get(script, [])

        if len(exp) != len(p_cells):
            add(HARD, 'B1-slot-count', script, plan_slots=len(exp), product_slots=len(p_cells))
        gate = plan['gates'].get('slots_' + script)
        if gate is not None and len(prod_lng) != gate:
            add(HARD, 'B1-lng-count', script, product_lng=len(prod_lng), gate=gate)

        drop_voice = collections.defaultdict(set)
        for k in drops:
            if k < len(s_cells):
                for kind, _chan, nm in s_cells[k]['tok']:
                    drop_voice[kind].add(nm)

        # 被删格携带的演出名若在原版归档里查无同名成员 ⇒ 字节层覆盖消化不了（「回退面」）
        def in_orig_any(kind, nm):
            low = s(nm).lower()
            arch = KIND_ARCH.get(kind) or orig_where.get(low)
            return bool(arch) and low in orig_tab.get(arch, {})

        # 删格残留**按产物实测**：`tool/writer.drop_units()` 已把被删行的演出前缀区
        # （语音/显示/BGM/图层/特效）一并摘除（见 doc/lessons-learned.md §16）⇒ 残留只可能
        # 来自「产物里真出现了被删格的名字」。在下面的逐格核对里累计：
        # B4/B6/B7 判为 residue 的格、B8 判为 drop-residue 的 bgm 差、以及单格携带多条
        # 语音触发（= 相邻语音触发之间没有 `14`，无对白连播）。
        res = collections.Counter()
        only = collections.defaultdict(set)
        burst = 0

        # 顶包改写点按**名字字节偏移**归到其后的最近一条 14（与承载图同口径）。
        # 判读表的 `slot` 记的是「显示指令之前的那一行」，两者实测差一格。
        s_14offs = [c['off'] for c in s_cells]
        rewrites = {}
        for rw in plan.get('reuse_rewrites', []):
            if rw['script'] != script:
                continue
            site = int(rw['offset'])
            owner = bisect.bisect_right(s_14offs, site) if s_14offs else None
            if owner is None or owner >= len(s_cells):
                add(HARD, 'D2-reuse-site-out-of-cells', script, name_offset=site,
                    n_14=len(s_14offs))
                continue
            if int(rw['slot']) != owner:
                if (script, str(rw['from']).upper(), str(rw['to']).upper()) in KNOWN_BENIGN_REUSE_SLOT_FIELD:
                    A['reuse_slot_field_benign_whitelisted'] += 1
                    continue
                add(REVIEW, 'D4-reuse-slot-field', script, name_from=s(rw['from']),
                    name_to=s(rw['to']), plan_slot=int(rw['slot']), owner_slot=owner,
                    note='表 `slot` 记的是显示指令**之前**那一行；产物里该改写落在其后'
                         '一条 `14` 的前奏里（与承载图归属口径一致）')
            rewrites[owner] = (rw['to'].encode('ascii', 'replace').upper(),
                               rw['from'].encode('ascii', 'replace').upper())
        # 原版复用名改写集合（脚本名义名 → 原版实际显示名），用于把 B6/B8 里
        # 完全由该复用解释的画面偏移判为良性（见 §51：KOT_003 KOT_12_007S→KOT_12_002B 即原版行为）。
        reuse_pairs = {(rw['from'].upper(), rw['to'].upper())
                       for rw in plan.get('reuse_rewrites', [])
                       if rw.get('script') == script}

        # 期望的直接携带值：块尾前奏 ⊕ 本格来源（后者为末值），再套顶包改写
        want_owns = []
        for j, (kind, idx) in enumerate(exp):
            src_cell = None
            if kind == 'steam' and idx < len(s_cells):
                src_cell = s_cells[idx]
            elif kind == 'orig' and idx < len(o_cells):
                src_cell = o_cells[idx]
            own = {}
            tr = tail.get(j)
            if tr is not None and tr < len(o_cells):
                own = merge_own(own, o_cells[tr]['own'])
            if src_cell is not None:
                own = merge_own(own, src_cell['own'])
            if kind == 'steam' and idx in rewrites:
                to, _frm = rewrites[idx]
                if own.get('cg') != _frm or to in (b'', b'????'):
                    add(HARD, 'D3-reuse-from-not-at-site', script, cell=j, src='%s:%d' % (kind, idx),
                        expect=s(_frm), got=s(own.get('cg')), to=s(to))
                else:
                    own['cg'] = to
            want_owns.append(own)
        want_effs = eff_chain(want_owns)

        for j, src in enumerate(exp):
            if j >= len(p_cells):
                break
            kind, idx = src
            pc = p_cells[j]
            # 无对白连播：同一格携带 **≥2 条**残留语音触发（名字属被删格）⇒ 相邻两条
            # 语音触发之间没有 `14`。单条同名出现可能只是还原行复用了同名语音，不算；
            # 合唱行（原版自身就是多触发一格）也不算。
            _resv = sum(1 for kk, _c, n in pc['tok']
                        if kk == 'voice' and n in drop_voice.get('voice', set()))
            if _resv > 1:
                burst = max(burst, _resv)
            base = s_cells[idx] if kind == 'steam' and idx < len(s_cells) else None
            obase = o_cells[idx] if kind == 'orig' and idx < len(o_cells) else None
            if base is None and obase is None:
                add(HARD, 'B2-source-out-of-range', script, cell=j, src_kind=kind, src_index=idx)
                continue
            tag = '%s:%d' % (kind, idx)
            wo = want_owns[j]
            want_voice, got_voice = wo.get('voice'), pc['own'].get('voice')
            want_cg, got_cg = wo.get('cg'), pc['own'].get('cg')

            # 文本
            if kind == 'steam' and idx in text_overrides:
                # 覆盖槽：计划声明该槽 zh 用原版行民汉（脚本指令未动）
                ov = text_overrides[idx]
                want_text = fan[ov] if ov < len(fan) else None
                have_official = ov < len(fan)
            elif kind == 'steam':
                want_text = off_lng[base['id']] if base['id'] < len(off_lng) else None
                have_official = base['id'] < len(off_lng)
            else:
                want_text = fan[idx] if idx < len(fan) else None
                have_official = idx < len(fan)
            got_text = prod_lng[pc['id']] if pc['id'] < len(prod_lng) else None
            if have_official and want_text is not None and txt_norm(got_text) != txt_norm(want_text):
                add(HARD, 'B3-text', script, cell=j, src=tag, lng_id_of_product_cell=pc['id'],
                    expect=want_text, got=got_text)
                B['text_bad'] += 1
            else:
                B['text_ok'] += 1

            # 语音
            if want_voice or got_voice:
                if want_voice == got_voice:
                    B['voice_ok'] += 1
                elif got_voice and got_voice in drop_voice.get('voice', set()) and kind == 'steam':
                    add(REVIEW, 'B4-voice-residue', script, cell=j, src=tag,
                        expect=s(want_voice), got=s(got_voice),
                        note='该语音号属被删格，删格未做语音点名删')
                    B['voice_residue'] += 1
                    res['res_voice'] += 1
                    if not in_orig_any('voice', got_voice):
                        only['voice'].add(s(got_voice))
                else:
                    add(HARD, 'B5-voice-shift', script, cell=j, src=tag,
                        expect=s(want_voice), got=s(got_voice))
                    B['voice_shift'] += 1

            # 画面（CG + 立绘通道）
            if want_cg or got_cg:
                if want_cg == got_cg:
                    B['cg_ok'] += 1
                elif got_cg and got_cg in drop_voice.get('cg', set()) and kind == 'steam':
                    add(REVIEW, 'B6-cg-residue', script, cell=j, src=tag,
                        expect=s(want_cg), got=s(got_cg))
                    B['cg_residue'] += 1
                    res['res_cg'] += 1
                    if not in_orig_any('cg', got_cg):
                        only['cg'].add(s(got_cg))
                elif (s(want_cg).upper(), s(got_cg).upper()) in reuse_pairs:
                    # 原版复用名改写：脚本名义 carry 名（from）与原版实际显示名（to）不同，
                    # 画面偏移完全由 reuse_rewrites 解释，产物与原版行为一致 ⇒ 非偏移。
                    A['b6_reuse_benign'] += 1
                else:
                    add(HARD, 'B6-cg-shift', script, cell=j, src=tag,
                        expect=s(want_cg), got=s(got_cg))
                    B['cg_shift'] += 1
            wsp, gsp = wo.get('sprite', {}), pc['own'].get('sprite', {})
            for chan in set(wsp) | set(gsp):
                if wsp.get(chan) != gsp.get(chan):
                    grp = ('B7-sprite-residue' if gsp.get(chan) in drop_voice.get('sprite', set())
                           else 'B7-sprite-shift')
                    if grp.endswith('residue'):
                        res['res_sprite'] += 1
                        if not in_orig_any('sprite', gsp.get(chan)):
                            only['sprite'].add(s(gsp.get(chan)))
                    add(REVIEW if grp.endswith('residue') else HARD, grp, script, cell=j, src=tag,
                        chan=s(chan), expect=s(wsp.get(chan)), got=s(gsp.get(chan)))
                    B[grp] += 1

            # 玩家可见面：本行读到时「在屏的画面」（语音逐行触发，由 B4/B5 管）
            we, ge = want_effs[j], pc['eff']
            for k, grp in (('cg', 'B8-picture'), ('bgm', 'B8-bgm')):
                wv, gv = we.get(k), ge.get(k)
                if wv == gv:
                    B['b8_ok'] += 1
                    continue
                cause = ('drop-residue' if gv in drop_voice.get(k, set()) else 'unknown')
                if k == 'cg' and (s(wv).upper(), s(gv).upper()) in reuse_pairs:
                    # 原版复用名改写解释的在屏画面偏移 ⇒ 良性（见 B6 同源说明）
                    A['b8_reuse_benign'] += 1
                    continue
                B['b8_bad_' + cause] += 1
                if k == 'bgm' and cause == 'drop-residue':
                    res['res_bgm'] += 1
                    if not in_orig_any('bgm', gv):
                        only['bgm'].add(s(gv))
                add(HARD, grp, script, cell=j, src=tag, expect=s(wv), got=s(gv), cause=cause)
            wl, gl = we.get('sprite', {}), ge.get('sprite', {})
            for chan in set(wl) | set(gl):
                if wl.get(chan) == gl.get(chan):
                    B['b8_ok'] += 1
                    continue
                gv = gl.get(chan)
                cause = ('drop-residue' if gv in drop_voice.get('sprite', set())
                         else 'unknown')
                B['b8_bad_' + cause] += 1
                add(HARD, 'B8-picture', script, cell=j, src=tag, chan=s(chan),
                    expect=s(wl.get(chan)), got=s(gv), cause=cause)

            # 资源解析面（还原段引用的名字）
            if kind == 'orig':
                B['restored_cells'] += 1
                for rk, nm, arch in refs_of(pc):
                    low = s(nm).lower()
                    arch = arch or orig_where.get(low) or steam_where.get(low)
                    if arch is None:
                        in_prod_any = any(low in tb for tb in prod_tab.values())
                        add(REVIEW, 'C0-name-absent-in-orig', script, cell=j, name=s(nm),
                            in_product=in_prod_any,
                            note='原版归档与 Steam 归档都无此名 ⇒ 原版脚本自身如此，'
                                 '还原逐字节照搬，非还原缺口')
                        continue
                    in_orig = low in orig_tab[arch]
                    in_steam = low in steam_tab[arch]
                    in_prod = low in prod_tab.get(arch, {})
                    if not in_orig and not in_steam:
                        add(HARD, 'C1-name-in-no-archive', script, cell=j, name=s(nm), arch=arch)
                    elif not in_orig and in_steam:
                        add(REVIEW, 'C2-steam-only-name', script, cell=j, name=s(nm), arch=arch)
                    elif not in_steam and not in_prod:
                        add(HARD, 'C3-copy-not-landed', script, cell=j, name=s(nm), arch=arch)
                    elif in_steam:
                        need_hash.add((arch, low))          # 两侧同名 ⇒ 必须核到原版字节

        # 删格残留（产物实测）汇总：只有产物里真出现了被删格的名字才算缺陷
        R['res_burst'] = max(R['res_burst'], burst)
        if any(res.values()):
            for kk in ('res_voice', 'res_cg', 'res_sprite', 'res_bgm'):
                R[kk] += res[kk]
            for kk in ('voice', 'cg', 'sprite', 'bgm'):
                R['res_only_' + kk] += len(only[kk])
            add(HARD, 'B9-drop-residue', script, dropped_cells=len(drops),
                voice=res['res_voice'], cg=res['res_cg'], sprite=res['res_sprite'],
                bgm=res['res_bgm'], voice_burst=burst,
                steam_only_names={kk: sorted(only[kk]) for kk in
                                  ('voice', 'cg', 'sprite', 'bgm') if only[kk]},
                note='产物里仍残留被删 Steam 行的演出指令：无对白连播语音、并把画面/BGM '
                     '改回 Steam 素材')

    # ── 内容复算：两侧同名且被还原段引用 ⇒ 产物字节必须等于原版字节 ──
    D = collections.Counter()
    by_arch = collections.defaultdict(set)
    for arch, low in need_hash:
        by_arch[arch].add(low)
    for arch, lows in sorted(by_arch.items()):
        ph = arc_hashes(delivered[arch], lows)
        oh = arc_hashes(os.path.join(args.orig_dir, arch), lows)
        for low in sorted(lows):
            D['checked'] += 1
            if low not in ph:
                add(HARD, 'C3-not-in-delivered', arch, name=low)
                continue
            if low not in oh:
                add(HARD, 'C7-absent-in-orig-archive', arch, name=low,
                    note='原名索引命中但原版归档内读不到成员')
                continue
            if ph[low] != oh[low]:
                if (arch.lower(), low) in keep_roster:
                    # 判定表显式判为「噪声/不动」（重编码噪声级差异，视觉/听觉等价）
                    # ⇒ 产物字节＝Steam 字节是**决策**，不是未覆盖
                    D['keep_noise'] += 1
                    continue
                add(HARD, 'C4-not-original-bytes', arch, name=low,
                    registered_overwrite=(arch.lower(), low) in ow_roster,
                    in_copy_roster=low in copy_roster)
                D['stale'] += 1
            else:
                D['equal'] += 1

    # ── 覆盖名单逐名落地复算（判定表 overwrite 子集）──
    canon = {a.lower(): a for a in RESOURCE_ARCHIVES}
    ow_by_arch = collections.defaultdict(set)
    for arch_low, low in ow_roster:
        arch = canon.get(arch_low)
        if arch is None:
            add(HARD, 'C6-overwrite-arch-unknown', arch_low, name=low)
            continue
        ow_by_arch[arch].add(low)
    for arch, lows in sorted(ow_by_arch.items()):
        ph = arc_hashes(delivered[arch], lows)
        oh = arc_hashes(os.path.join(args.orig_dir, arch), lows)
        for low in sorted(lows):
            D['overwrite_roster'] += 1
            if low not in ph or low not in oh:
                add(HARD, 'C5-overwrite-missing-member', arch, name=low,
                    in_delivered=low in ph, in_orig=low in oh)
            elif ph[low] != oh[low]:
                add(HARD, 'C5-overwrite-not-landed', arch, name=low)

    # ── 顶包改写点：按**名字字节偏移**定归属格，在产物上核落地 ──
    prod_cells_cache = {}
    for rw in plan.get('reuse_rewrites', []):
        script = rw['script']
        if script not in prod_raw:
            add(HARD, 'D0-reuse-script-absent', script)
            continue
        if script not in scope:
            add(REVIEW, 'D0-reuse-script-out-of-scope', script, name_to=s(rw['to']))
            continue
        host = plan['hosts'].get(script, {})
        if host.get('kind') != 'host':
            add(HARD, 'D0-reuse-host-not-built', script, kind=host.get('kind'))
            continue
        if script not in prod_cells_cache:
            s_offs = [c['off'] for c in scan_cells(ws2.decode(steam_raw[script]))]
            prod_cells_cache[script] = (s_offs, scan_cells(ws2.decode(prod_raw[script])))
        s_offs, p_cells = prod_cells_cache[script]
        site = int(rw['offset'])
        owner = bisect.bisect_right(s_offs, site)
        if not s_offs or owner >= len(s_offs):
            add(HARD, 'D2-reuse-site-out-of-cells', script, name_offset=site,
                n_14=len(s_offs), plan_slot=rw['slot'])
            continue
        seq_only = expected_sequence(host, len(s_offs))[0]
        pos = [j for j, (k, v) in enumerate(seq_only) if k == 'steam' and v == owner]
        if len(pos) != 1:
            add(HARD, 'D1-reuse-slot-not-unique', script, owner_slot=owner,
                plan_slot=rw['slot'], hits=pos[:4])
            continue
        got = [nm for _r, nm, _a in refs_of(p_cells[pos[0]])]
        want = rw['to'].encode('ascii', 'replace').upper()
        old = rw['from'].encode('ascii', 'replace').upper()
        if want not in got:
            add(HARD, 'D2-reuse-rewrite-missing', script, product_cell=pos[0],
                owner_slot=owner, expect=s(want), got=[s(x) for x in got])
        else:
            D['reuse_ok'] += 1
        if old in got:
            add(HARD, 'D3-reuse-old-name-kept', script, product_cell=pos[0], name=s(old))

    # ── 报告 ──
    total = {
        'A.pairs': A['pairs'], 'A.voice_equal': A['voice_equal'],
        'A.voice_diff': A['voice_diff'], 'A.voice_one_side': A['voice_one_side'],
        'A.voice_diff_carried': A['voice_diff_carried'],
        'A.voice_diff_carried_latin': A['voice_diff_carried_latin'],
        'A.voice_diff_other': A['voice_diff_other'],
        'A.cg_diff': A['cg_diff'], 'A.pair_oob': A['pair_oob'],
        'B.restored_cells': B['restored_cells'],
        'B.text_ok': B['text_ok'], 'B.text_bad': B['text_bad'],
        'B.voice_ok': B['voice_ok'], 'B.voice_shift': B['voice_shift'],
        'B.voice_residue': B['voice_residue'],
        'B.cg_ok': B['cg_ok'], 'B.cg_shift': B['cg_shift'], 'B.cg_residue': B['cg_residue'],
        'B.line_picture_ok': B['b8_ok'], 'B.line_picture_bad': B['b8_bad_unknown'] + B['b8_bad_drop-residue'],
        'B.bad_by_residue': B['b8_bad_drop-residue'], 'B.bad_unexplained': B['b8_bad_unknown'],
        'B.sprite_shift': B['B7-sprite-shift'], 'B.sprite_residue': B['B7-sprite-residue'],
        'R.residue_voice': R['res_voice'], 'R.residue_cg': R['res_cg'],
        'R.residue_sprite': R['res_sprite'], 'R.residue_bgm': R['res_bgm'],
        'R.residue_steam_only_voice': R['res_only_voice'],
        'R.residue_steam_only_cg': R['res_only_cg'],
        'R.residue_steam_only_sprite': R['res_only_sprite'],
        'R.residue_steam_only_bgm': R['res_only_bgm'],
        'R.residue_voice_burst': R['res_burst'],
        'D.hash_checked': D['checked'], 'D.keep_noise': D['keep_noise'], 'D.hash_equal': D['equal'], 'D.hash_stale': D['stale'],
        'D.overwrite_roster': D['overwrite_roster'], 'D.reuse_ok': D['reuse_ok'],
        'D.reuse_total': len(plan.get('reuse_rewrites', [])),
        'A.cg_diff_benign_whitelisted': A['cg_diff_benign_whitelisted'],
        'A.reuse_slot_field_benign_whitelisted': A['reuse_slot_field_benign_whitelisted'],
        'A.b6_reuse_benign': A['b6_reuse_benign'],
        'A.b8_reuse_benign': A['b8_reuse_benign'],
    }
    lines = ['# 文本-语音-CG 一致性校验', '',
             '- 范围：%d 个在还原范围内的脚本（A-1 整脚本 %d + 宿主 %d）'
             % (len(scope), len(plan['A1']), sum(1 for h in plan['hosts'].values() if h['kind'] == 'host')),
             '- 信源：产物 `%s`、基线 `backup/`、原版 `%s`' % (
                 args.asset.replace(ROOT, '<root>'), args.orig_dir.replace(ROOT, '<root>')),
             '', '## 读数', '', '| 项 | 值 |', '|---|---|']
    for k, v in total.items():
        lines.append('| %s | %d |' % (k, v))
    groups = collections.Counter((lv, gp) for lv, gp, _x, _d in finds)
    lines += ['', '## 分组计数', '', '| 级别 | 组 | 条数 |', '|---|---|---|']
    for (lv, gp), n in sorted(groups.items()):
        lines.append('| %s | %s | %d |' % (lv, gp, n))
    lines.append('')
    lines.append('## 明细（每组最多 %d 条）' % args.max_rows)
    for gp in sorted({g for _l, g, _x, _d in finds}):
        rows = [f for f in finds if f[1] == gp]
        lines += ['', '### %s · %s（%d 条）' % (rows[0][0], gp, len(rows)), '']
        for _lv, _g, script, d in rows[:args.max_rows]:
            lines.append('- `%s` %s' % (script, json.dumps(d, ensure_ascii=False, sort_keys=True)))
        if len(rows) > args.max_rows:
            lines.append('- …（其余 %d 条见 tmp/verify_sync_findings.json）'
                         % (len(rows) - args.max_rows))
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, 'w', encoding='utf-8', newline='\n') as f:
        f.write('\n'.join(lines) + '\n')
    with open(os.path.join(ROOT, 'tmp', 'verify_sync_findings.json'), 'w', encoding='utf-8',
              newline='\n') as f:
        json.dump([{'level': lv, 'group': gp, 'key': s0, **d} for lv, gp, s0, d in finds], f,
                  ensure_ascii=False, indent=0)
        f.write('\n')

    hard = collections.Counter(g for lv, g, _x, _d in finds if lv == HARD)
    rev = collections.Counter(g for lv, g, _x, _d in finds if lv == REVIEW)
    print('report: %s' % args.out.replace(ROOT, '<root>'))
    print('scope %d ; findings %d' % (len(scope), len(finds)))
    for name, v in sorted(total.items()):
        print('  %-24s %d' % (name, v))
    print('HARD:')
    for g, n in sorted(hard.items()) or [('(none)', 0)]:
        print('  %-28s %d' % (g, n))
    if not hard:
        print('  (none)')
    print('REVIEW:')
    for g, n in sorted(rev.items()):
        print('  %-28s %d' % (g, n))
    if not rev:
        print('  (none)')
    return 1 if hard else 0


def txt_norm(t):
    return None if t is None else t.replace('\r\n', '\n').strip()


if __name__ == '__main__':
    sys.exit(main())
