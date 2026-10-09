# -*- coding: utf-8 -*-
"""插入计划器（管线步 3）：判读台账 + 承载图 + 改名表 + 双语语料 → resource/restore_plan.json。

产物（每脚本）：
  A-1   kind=whole  —— 整脚本经 ws2conv.convert_script 转换；槽位文本 = fan_cn 按原版 idx 1:1。
  宿主  kind=host   —— drops/inserts/external + slot_sources + slot_texts（最终槽位序：
                          保留格 = 官方 .lng 按旧 idx 直索引（CO1_020 空洞天然跳过）；
                          插入格 = resource/fan_cn 按原版行 idx）。
  跳转  kind=jump   —— 5 处入口尾跳改回原版目标（等长名字节替换）。

资源需求：扫还原区间（A-1 全脚本）的 0x28(0x2e 语音体/SE)、0x1e(BGM)、0x33(PNG)、
0x34(PNA/PNG) 引用 → 分派三桶：Steam 已有且等同原版（`have`）/ Steam 缺失（`copy`，
从原版对应归档复制、继承原名，归档归属按「原版成员名 → 归档」实测索引）/
同名成员换内容（`overwrite`）。**`overwrite` 的名单来自**：
  · 图像＝判定表 `resource/censor_map.json` 的 `action=overwrite` 子集；
  · 语音＝判定表 `resource/voice_conflict_map.json` 的 `action=overwrite` 子集
    （噪声类 `action=keep` 不动）。
两表都**逐名**入覆盖面、**不以「被还原内容引用」为门槛**（口径见 doc/resource-naming.md §1／§3）。
**没有 `rename` 分类**——隔离改名路线已取消。

顶包（`class=reuse`）另出 `reuse_rewrites`：按判定表成员的 `surviving_sites`
（存活格核对结论）取出**改写**的调用点，连同其目标名的资源分派。

闸（只看表，任一不过即退出 1）：台账全覆盖 / 插入锚不落被删格 / 锚内行序单调 /
插入块零 0f 且 14 数=行数 / 跨块跳转全解析 / 槽位文本无缺失 / 资源分派无遗漏 /
改名表不含判定表成员（§7.5）/ 顶包名有存活格核对结论（§7.7）/
**语音覆盖名单数 = 判定表 overwrite 数**（名单外不得漏）。
"""
import collections
import glob
import hashlib
import json
import os
import struct
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
from tool import arcbuild, ws2, ws2dis, lng, scriptext, fancn  # noqa: E402
from tool import v5lib  # noqa: E402
from tool import paths  # noqa: E402
from tool.ws2conv import load_orig_formats, parse as conv_parse, convert_script, REBASE_OPS  # noqa: E402
from tool import writer  # noqa: E402

A1_SCRIPTS = ['ASA_002', 'ASA_004', 'YOR_003', 'YOR_005', 'YOR_007']
JUMP_REVERTS = [('ASA_001', 'ASA_003', 'ASA_002'), ('ASA_003', 'ASA_005', 'ASA_004'),
                ('YOR_002', 'YOR_004', 'YOR_003'), ('YOR_004', 'YOR_006', 'YOR_005'),
                ('YOR_006', 'YOR_008', 'YOR_007')]
OUT_JSON = os.path.join(ROOT, 'resource', 'restore_plan.json')
OUT_MD = os.path.join(ROOT, 'tmp', 'restore_plan.md')

_res_cache = {}


def rio_dec(side):
    """{script: 解码字节}，side='steam'|'orig'。"""
    if side not in _res_cache:
        base = paths.STEAM if side == 'steam' else paths.orig_dir()
        out = {}
        for nb, d in arcbuild.read_raw(os.path.join(base, 'Rio.arc')):
            try:
                n = nb.decode('utf-16le')
            except UnicodeDecodeError:
                continue
            if n.lower().endswith('.ws2'):
                out[n[:-4].upper()] = ws2.decode(d)
        _res_cache[side] = out
    return _res_cache[side]


def arc_names(path):
    """只读归档条目表 → {成员名小写: 原始名}（不读数据区）。"""
    with open(path, 'rb') as f:
        head = f.read(8)
        count, table_size = struct.unpack('<II', head)
        tbl = f.read(table_size)
    out, p = {}, 0
    for _ in range(count):
        size, rel = struct.unpack_from('<II', tbl, p)
        p += 8
        q = p
        while tbl[q:q + 2] != b'\x00\x00':      # 逐 UTF-16 字符走到 U+0000 终止符
            q += 2
        name = tbl[p:q].decode('utf-16le')
        p = q + 2
        out[name.lower()] = name
    return out


def member_hashes(path, low_names):
    """只读条目表 + 按需 seek 读成员字节 → {小写名: sha256}（只算 low_names 内的名）。

    语音同名冲突的机械判据需要逐名比两侧内容，而 `VOICE.arc` 单档 ~800MB，
    整档读入内存（`arcbuild.read_raw`）不划算 ⇒ 这里只 seek 需要的成员。
    偏移语义（`rel` 相对 `8 + table_size`）见 `tool/arcbuild.py` 文档。
    """
    want = set(low_names)
    out = {}
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


def load_cg_sites():
    """resource/cg_site_rewrites.json：保留行的事件 CG 显示点缺口 ⇒ {script: [site]}。"""
    p = os.path.join(ROOT, 'resource', 'cg_site_rewrites.json')
    out = collections.defaultdict(list)
    if os.path.exists(p):
        for site in json.load(open(p, encoding='utf-8')).get('sites', []):
            out[site['script']].append(site)
    return out


def load_ledgers():
    """{script: [块条目]}（rereview 除外）。"""
    led = collections.defaultdict(list)
    for p in sorted(glob.glob(os.path.join(ROOT, 'resource', 'adjudication', '*.jsonl'))):
        s = os.path.basename(p)[:-6]
        if s.startswith('rereview'):
            continue
        with open(p, encoding='utf-8') as f:
            for line in f:
                if line.strip():
                    led[s].append(json.loads(line))
    return led


def official_lng(script):
    """官方 zh-CN .lng 的条目列表（按 idx 直索引；缺失脚本返回 None）。"""
    zh_arc = os.path.join(paths.STEAM, 'zh-CN', 'Rio.arc')
    for nb, d in arcbuild.read_raw(zh_arc):
        n = nb.decode('utf-16le', 'replace')
        if n.lower() == script.lower() + '.lng':
            return lng.parse_lng_tolerant(d, key=lng.KEY_STEAM_ZHCN)
    return None


def fan_texts(script):
    """插入格的中文：`resource/fan_cn/{script}.json` 按原版行 idx 展开。

    ⚠️ 该 JSON 是**扁平映射** `{"0": 文本, "1": 文本}`（口径见 `tool/fancn.py`），
    既不是列表、也没有 `texts` 键。**不得对它直接 for-in**——那会迭代出键
    （行号字符串）并把行号当正文写进交付（2026-10-06 复验 D1：8,010 个槽位
    全部落成行号）。统一走 `tool.fancn.load_texts()`。
    """
    p = os.path.join(ROOT, 'resource', 'fan_cn', script + '.json')
    if not os.path.exists(p):
        return None
    return fancn.load_texts(script)


def carrier_row_slot(script):
    """承载图 1:1 映射：{原版行: steam 槽位}（anchor/match 块内线性内插）。"""
    out = {}
    for b in v5lib.carrier()[script]['blocks']:
        o, s = b.get('orig'), b.get('steam')
        if not o or not s:
            continue
        if b['kind'] in ('anchor', 'match'):
            for r in range(o[0], o[1] + 1):
                k = s[0] + (r - o[0])
                if k <= s[1]:
                    out[r] = k
    return out


def scan_resources(orig_dec, spans, ofmt):
    """还原 span（指令下标 [i0,i1) 列表）内的资源引用。"""
    instrs, _tail = conv_parse(orig_dec, ofmt)
    offs, p = [], 0
    for op, ops in instrs:
        offs.append(p)
        p += 1 + len(ops)
    need = collections.defaultdict(set)
    for i0, i1 in spans:
        for j in range(i0, i1):
            op, ops = instrs[j]
            if op not in (0x1E, 0x28, 0x33, 0x34):
                continue
            parts = ops.split(b'\x00')
            if len(parts) < 2:
                continue
            chan = parts[0].decode('cp932', 'replace').upper()
            fname = parts[1].decode('cp932', 'replace').upper()
            if not fname:
                continue
            if op == 0x28:
                need['voice' if chan.startswith('CHAR') else 'se'].add(fname)
            elif op == 0x1E:
                need['bgm'].add(fname)
            elif op == 0x33:
                need['png'].add(fname)
            else:
                (need['pna'] if fname.endswith('.PNA') else need['png']).add(fname)
    return need


def row_of_target(o14off, tgt):
    """跳转目标解码偏移 → 其归属行（其后的第一条 14；超出末行归末行）。"""
    import bisect
    i = bisect.bisect_left(o14off, tgt)
    return len(o14off) - 1 if i >= len(o14off) else i


def build_host_plan(script, blocks, ofmt, gates, ren):
    steam_dec = rio_dec('steam')[script]
    orig_dec = rio_dec('orig')[script]
    drops, inserts, ext = [], [], {}
    text_overrides = {}     # steam 槽位 → 原版行（zh 交付该槽改用民汉，脚本指令不动）
    row_slot = carrier_row_slot(script)
    # `text_override`（民汉覆盖）的适用前提＝**该格是保留格**（两侧判定为同一行、
    # 仅官中译得差）。差分内容（Steam 改写/顶替/净化）**不得走 text**——
    # 它必须走 drop/rebind 的正常流程；那样处理之后，该槽的 zh 交付本来就是民汉
    # （`slot_texts` 对 `('orig', row)` 源取民汉）。
    suspect = {}
    for b in v5lib.carrier()[script.upper()]['blocks']:
        for p in (b.get('content_suspect') or []):
            suspect[p['steam_slot']] = p
    for e in blocks:
        for c in e.get('cells', []):
            if c['action'] == 'rebind':
                drops.append(c['slot'])
                inserts.append((c['slot'], c['bind_orig_row'], c['bind_orig_row']))
            elif c['action'] == 'drop':
                drops.append(c['slot'])
            elif c['action'] == 'keep':
                if not c.get('text_override'):
                    continue
                # 闸①：民汉覆盖只能挂在保留格上
                # 闸②：两侧语音号不一致 ⇒ 该对不是「同一行」，text 覆盖前提不成立
                assert c['slot'] not in suspect, \
                    '%s: 槽 %d 判为保留格却登记 text_override，但该对语音号不一致（%s→%s）' \
                    ' ⇒ 属差分内容，必须走 drop/rebind' % (script, c['slot'],
                                                    suspect[c['slot']].get('orig_voice'),
                                                    suspect[c['slot']].get('steam_voice'))
                assert c['slot'] not in text_overrides, \
                    '%s: 槽 %d 重复登记 text 覆盖' % (script, c['slot'])
                text_overrides[c['slot']] = c['bind_orig_row']
            elif c['action'] == 'text':
                raise AssertionError(
                    '%s: 槽 %d 用了已废弃的独立 action="text"；民汉覆盖只能作为保留格的属性'
                    '（action="keep" + text_override=true + bind_orig_row）——差分内容请走'
                    ' drop/rebind' % (script, c['slot']))
        for ins in e.get('inserts', []):
            a = ins['after_slot']
            a = -1 if a == -1 else a
            inserts.append((a, ins['orig_rows'][0], ins['orig_rows'][1]))
    # 画面还原：保留行上的「事件 CG 显示点」缺口（resource/cg_site_rewrites.json）
    # 处置与 rebind 同形——drop 该保留槽 + 插入原版行（随行带入 `0x33` 显示指令），
    # 资源扫描会把该 CG 成员并入 resources.copy。
    cg_sites = []
    for site in CG_SITES.get(script, []):
        k, r = site['slot'], site['orig_row']
        assert k not in drops, '%s: cg_site 槽 %d 已登记为删格' % (script, k)
        assert not any(a0 <= r <= b0 for _a0, a0, b0 in inserts),             '%s: cg_site 原版行 %d 已在插入区间内' % (script, r)
        drops.append(k)
        inserts.append((k, r, r))
        cg_sites.append({'slot': k, 'orig_row': r, 'name': site['name']})
    drops = sorted(set(drops))
    # text 覆盖槽不得同时被删（两套动作对同一格互斥）
    clash = text_overrides.keys() & set(drops)
    assert not clash, '%s: 槽 %s 同时登记 text 覆盖与删格' % (script, sorted(clash))
    if not drops and not inserts and not text_overrides:
        # 全 keep（典型 = 机械锚错位假象）：宿主零改动，官方 .lng 原样保留
        return {'kind': 'skip'}
    kept = [s for s in range(len(v5lib.rows('steam', script))) if s not in set(drops)]
    kept_set = set(kept)

    def norm_anchor(a):
        """锚normalize：'tail' → 末保留格；被删格/越界 → 回退到前一个保留格；-1 保持。"""
        if a == -1:
            return -1
        if a == 'tail':
            a = kept[-1] if kept else -1
            return a if a in kept_set else -1
        while a not in kept_set and a >= 0:
            a -= 1
        return a if a in kept_set else -1

    # 锚 normalize + 按锚聚合 + 行序单调
    by_anchor = collections.defaultdict(list)
    for a, r0, r1 in sorted(inserts, key=lambda x: (norm_anchor(x[0]), x[1])):
        by_anchor[norm_anchor(a)].append((r0, r1))
    ins_ranges, last_r = [], -1
    for a in sorted(by_anchor):
        for r0, r1 in by_anchor[a]:
            assert r0 > last_r, '%s: 插入区间原版行序回跳（锚 %d）' % (script, a)
            last_r = r1
    for a, ranges in sorted(by_anchor.items()):
        for r0, r1 in ranges:
            ins_ranges.append((a, r0, r1))

    # 跨块跳转解析
    oinstrs, _t = conv_parse(orig_dec, ofmt)
    ooff, p = [], 0
    for op, ops in oinstrs:
        ooff.append(p)
        p += 1 + len(ops)
    o14 = [j for j, (op, ops) in enumerate(oinstrs) if op == 0x14]
    covered = []        # (start_off, end_off) 字节区间（插入 span）
    for a, r0, r1 in ins_ranges:
        i0 = o14[r0 - 1] + 1 if r0 > 0 else 0
        i1 = o14[r1] + 1        # 与 writer.block_span 同口径：右端收到 r1 的 14 之后
        covered.append((ooff[i0], ooff[i1] if i1 < len(oinstrs) else len(orig_dec)))
    for j, (op, ops) in enumerate(oinstrs):
        if op not in REBASE_OPS or not any(a <= ooff[j] < b for a, b in covered):
            continue
        for k in REBASE_OPS[op]:
            v = struct.unpack_from('<I', ops, k)[0] if len(ops) >= k + 4 else 0
            if not v or any(a <= v < b for a, b in covered):
                continue
            r = row_of_target([ooff[t] for t in o14], v)
            s = row_slot.get(r)
            if s is None:
                # 目标落在原版结尾（末行 14 之后的流程控制）⇒ 映射到宿主结尾
                assert v > ooff[o14[-1]], \
                    '%s: 跨块跳转 %#x@%#x 归属行 %d 无承载且非结尾' % (script, v, ooff[j], r)
                ext[ooff[j]] = 'tail_end'
            else:
                assert s in kept_set, \
                    '%s: 跨块跳转 %#x@%#x 归属行 %d 的槽 %d 已被删' % (script, v, ooff[j], r, s)
                ext[ooff[j]] = s

    plan = {'drops': drops,
            'inserts': [(a, r0, r1) for a, r0, r1 in ins_ranges],
            'external': ext,
            # 匹配行文本覆盖（2026-10-07 口径）：steam 槽位 → 原版行，zh 交付该槽
            # 用民汉、脚本指令不动。verify_sync 的 B3 文本核对按此声明取期望文本。
            'text_overrides': {str(k): v for k, v in sorted(text_overrides.items())},
            'cg_sites': cg_sites}
    res = writer.rebuild_host(steam_dec, orig_dec, plan, ofmt)
    assert res['ok'] and res['fix_bad'] == 0, \
        '%s: rebuild fail ok=%s fix_bad=%d n14=%d n_slots=%d pool=%d' % (
            script, res['ok'], res['fix_bad'], res['n14'], res['n_slots'], res['pool'])

    # 槽位文本
    off_lng = official_lng(script)
    fan = fan_texts(script)
    slot_texts = []
    overrides_hit = set()
    for kind, key in res['slot_sources']:
        if kind == 'steam':
            if key in text_overrides:
                # 匹配行文本覆盖：该槽 zh 改用原版行的民汉（脚本指令不动）
                row = text_overrides[key]
                assert fan is not None and 0 <= row < len(fan), \
                    '%s: 覆盖槽 %d 的原版行 %d 无民汉文本' % (script, key, row)
                slot_texts.append(fan[row])
                overrides_hit.add(key)
            else:
                assert off_lng is not None and 0 <= key < len(off_lng), \
                    '%s: 保留槽 idx %d 无官方条目' % (script, key)
                slot_texts.append(off_lng[key])
        else:
            assert fan is not None and 0 <= key < len(fan), \
                '%s: 插入行 %d 无民汉文本' % (script, key)
            slot_texts.append(fan[key])
    # 闸：登记的覆盖必须全部落到产物槽位（被别的条目删掉的槽在这里暴露）
    missed = set(text_overrides) - overrides_hit
    assert not missed, '%s: text 覆盖槽 %s 未落到任何产物槽（被删或越界）' % (script, sorted(missed))
    gates['text_overrides_%s' % script] = len(overrides_hit)

    # 资源需求
    spans = []
    for a, r0, r1 in ins_ranges:
        i0 = o14[r0 - 1] + 1 if r0 > 0 else 0
        i1 = o14[r1] + 1        # 与 writer.block_span 同口径：右端收到 r1 的 14 之后
        spans.append((i0, i1))
    need = scan_resources(orig_dec, spans, ofmt)
    names = {n.lower(): ren[n.lower()] for kinds in need.values() for n in kinds
             if n.lower() in ren}
    gates['slots_%s' % script] = len(slot_texts)
    plan['names'] = names
    # 产物行序 → 来源（供逐行核对/机检）：[['steam', 槽], ['orig', 行], ...]
    # 注意：用**产物行序**排，`slot_sources` 就是 rebuild_host 发出的顺序。
    plan['slot_sources'] = [[k, v] for k, v in res['slot_sources']]
    return {'kind': 'host', 'plan': plan, 'slot_texts': slot_texts,
            'resources': {k: sorted(v) for k, v in need.items()},
            'n_drops': len(drops), 'n_insert_rows': sum(r1 - r0 + 1 for _, r0, r1 in ins_ranges)}


def build_whole_plan(script, ofmt, gates, ren):
    orig_dec = rio_dec('orig')[script]
    fan = fan_texts(script)
    assert fan is not None, '%s: 缺 fan_cn' % script
    instrs, _t = conv_parse(orig_dec, ofmt)
    n14 = sum(1 for op, _ in instrs if op == 0x14)
    n0f = sum(op for op, ops in instrs if op == 0x0F and False) or sum(
        ops[1] for op, ops in instrs if op == 0x0F)
    assert n0f == 0, '%s: 整脚本含 0f（%d 条目）——需另行裁定' % (script, n0f)
    assert n14 == len(fan), '%s: 14 数 %d != fan 槽数 %d' % (script, n14, len(fan))
    need = scan_resources(orig_dec, [(0, len(instrs))], ofmt)
    names = {n.lower(): ren[n.lower()] for kinds in need.values() for n in kinds
             if n.lower() in ren}
    gates['slots_%s' % script] = len(fan)
    return {'kind': 'whole', 'slots': len(fan), 'texts': fan, 'names': names,
            'resources': {k: sorted(v) for k, v in need.items()}}


def os_enc(script):
    """orig 侧原始编码字节（rotate-6 未解码）。"""
    for nb, d in arcbuild.read_raw(os.path.join(paths.orig_dir(), 'Rio.arc')):
        n = nb.decode('utf-16le', 'replace')
        if n.lower() == script.lower() + '.ws2':
            return d
    raise KeyError(script)


def main():
    ofmt = load_orig_formats(paths.orig_dir())
    led = load_ledgers()
    global CG_SITES
    CG_SITES = load_cg_sites()
    gates = {}
    errors = []
    plans = {'A1': {}, 'hosts': {}, 'jumps': [list(j) for j in JUMP_REVERTS]}
    rename = json.load(open(os.path.join(ROOT, 'resource', 'rename_map.json'), encoding='utf-8'))
    # 取名映射已停用（resource-naming.md §1／§8）：同名冲突走整名覆盖，插入段照抄
    # 原版脚本里的名字即为正确 ⇒ `plan.names` 恒为空。这里仍读 `rename_map` 只为
    # 下面那道互斥闸（§7.5）核对「改名表不得含判定表成员」。
    ren = {}

    for s in A1_SCRIPTS:
        try:
            plans['A1'][s] = build_whole_plan(s, ofmt, gates, ren)
        except AssertionError as ex:
            errors.append('%s: %s' % (s, ex))

    host_scripts = sorted(s for s, blocks in led.items() if s not in A1_SCRIPTS)
    for s in host_scripts:
        try:
            plans['hosts'][s] = build_host_plan(s, led[s], ofmt, gates, ren)
        except AssertionError as ex:
            errors.append('%s: %s' % (s, ex))

    # ── 资源分派：copy（Steam 缺 ⇒ 补入并继承原名）/ overwrite（同名成员换内容）/
    #    have（Steam 已有且内容等同原版）──
    # 覆盖的合法性来源（两条，见 doc/resource-naming.md §2–§3）：
    #   · 图像（.png／.pna）：判定表 `resource/censor_map.json` 的 `action=overwrite`
    #     子集（人工逐张看图定案）；
    #   · 语音：判定表 `resource/voice_conflict_map.json` 的 `action=overwrite` 子集
    #     （`class=noise` 一律 keep ⇒ 保留 Steam 字节）。
    #     need 驱动的同名不同字节分支**只做遵守 + 缺录报警**，不得自行定类：
    #     实测 `AGE_3942.ogg`（判定表 `noise/keep`）曾被它当 overwrite 加进来，
    #     被「名单数＝替换数」闸拦住（2026-10-08）。
    # **没有 rename 分类**——隔离改名路线已取消（§1）：插入段照抄原版脚本里的名字
    # 即为正确，覆盖落盘后原名承载的就是原版画面。
    censor = json.load(open(os.path.join(ROOT, 'resource', 'censor_map.json'), encoding='utf-8'))
    vmap = json.load(open(os.path.join(ROOT, 'resource', 'voice_conflict_map.json'), encoding='utf-8'))
    v_roster = {m['name'].upper(): m['action'] for m in vmap['members']}
    ow_index = {}
    for m in list(censor['members']) + list(vmap['members']):
        if m['action'] == 'overwrite':
            ow_index[(m['archive'].lower(), m['name'].lower())] = m
    # 闸（§7.5）：判定表 overwrite 成员不得同时出现在改名表
    for k in ('voice', 'sprite', 'mos', 'est'):
        for e in rename.get(k, []):
            sa = (e.get('source_archive') or '').lower()
            if sa and (sa, e['orig'].lower()) in ow_index:
                errors.append('改名表含判定表 overwrite 成员 %s/%s ⇒ 中止写盘（resource-naming.md §7.5）'
                              % (sa, e['orig']))

    steam_names = {}
    for arch in ('VOICE.arc', 'Chip1.arc', 'CHIP2.arc', 'CHIP3.arc', 'CHIP4.arc',
                 'CHIP5.arc', 'CHIP6.arc', 'GRAPHIC.arc', 'SE.arc', 'BGM.arc'):
        steam_names[arch] = arc_names(os.path.join(paths.STEAM, arch))
    orig_index = {}
    for arch in ('VOICE.arc', 'Chip1.arc', 'CHIP2.arc', 'CHIP3.arc', 'CHIP4.arc',
                 'CHIP5.arc', 'CHIP6.arc', 'GRAPHIC.arc', 'SE.arc', 'BGM.arc'):
        for low in arc_names(os.path.join(paths.orig_dir(), arch)):
            orig_index.setdefault(low, arch)
    resource_plan = {'copy': [], 'overwrite': [], 'have': 0}
    seen = set()
    allneed = collections.defaultdict(set)
    for grp in ('A1', 'hosts'):
        for s, pl in plans[grp].items():
            if pl.get('kind') == 'skip':
                continue
            for kind, names in pl['resources'].items():
                for n in names:
                    allneed[kind].add(n)
    arch_of = {'voice': 'VOICE.arc', 'se': 'SE.arc', 'bgm': 'BGM.arc', 'png': None, 'pna': 'GRAPHIC.arc'}

    # 语音同名冲突候选：先按引用面取集合，再逐名比两侧哈希（只 seek 这些成员）
    voice_low = {n.lower() for n in allneed.get('voice', ())}
    v_steam = member_hashes(os.path.join(paths.STEAM, 'VOICE.arc'), voice_low) if voice_low else {}
    v_orig = (member_hashes(os.path.join(paths.orig_dir(), 'VOICE.arc'), voice_low)
              if voice_low else {})

    def classify(n, kind):
        """把资源名分派到 copy／overwrite／have（同一次运行内同名只判一次）。"""
        low = n.lower()
        if low in seen:
            return
        seen.add(low)
        arch = arch_of.get(kind) or orig_index.get(low)
        if arch is None:
            errors.append('资源 %s（%s）原版全归档找不到归属' % (n, kind))
            return
        if low not in steam_names.get(arch, {}):
            resource_plan['copy'].append({'kind': kind, 'archive': arch, 'orig': n})
        elif (arch.lower(), low) in ow_index:
            m = ow_index[(arch.lower(), low)]
            resource_plan['overwrite'].append({'kind': kind, 'archive': arch,
                                               'name': m['name'], 'orig_name': m['orig_name']})
        elif kind == 'voice' and v_steam.get(low) != v_orig.get(low):
            act = v_roster.get(low.upper())
            if act is None:
                errors.append('语音 %s 同名不同字节但不在 voice_conflict_map ⇒ 判定表需补录'
                              '（resource-naming.md §3）' % n)
            elif act == 'overwrite':
                resource_plan['overwrite'].append({'kind': kind, 'archive': arch,
                                                   'name': n, 'orig_name': n})
            else:                       # noise ⇒ keep：保留 Steam 字节
                resource_plan['have'] += 1
        else:
            resource_plan['have'] += 1

    for kind, names in sorted(allneed.items()):
        for n in sorted(names):
            classify(n, kind)

    # 判定表的覆盖子集**逐名**进入覆盖面（§7.9）：不因「未被还原内容引用」而漏
    # ——覆盖不改名、无引用面代价，凡非噪声者一律覆盖；漏名不报错、只是画面/发音
    # 仍是 Steam 版，故必须由名单逐名兜住。图像表与语音表一并处理。
    for (_alow, nlow), m in sorted(ow_index.items()):
        if nlow in seen:
            continue
        seen.add(nlow)
        ext = os.path.splitext(m['name'])[1].lower()
        resource_plan['overwrite'].append({
            'kind': {'.png': 'png', '.pna': 'pna', '.ogg': 'voice'}.get(ext, 'png'),
            'archive': m['archive'], 'name': m['name'], 'orig_name': m['orig_name']})
    # 闸：语音覆盖名单数必须等于判定表 overwrite 数（名单外不得漏）
    v_ow = sum(1 for x in resource_plan['overwrite'] if x['kind'] == 'voice')
    v_want = sum(1 for m in vmap['members'] if m['action'] == 'overwrite')
    if v_ow != v_want:
        errors.append('语音覆盖名单数 %d != 判定表 overwrite 数 %d ⇒ 中止写盘（resource-naming.md §3）'
                      % (v_ow, v_want))

    # ── 顶包（class=reuse）存活格核对结论 → 调用点改写 ──
    # 结论落在判定表成员的 `surviving_sites`：逐点写明它对齐到的原版行显示哪张图、
    # 因此改写还是不改写。只有 `decision == 'rewrite'` 的点才改写，改写目标名须在
    # 原版归档在位（Steam 缺则按 copy 补入）。见 doc/resource-naming.md §3／§7.7。
    reuse_rewrites = []
    for m in censor['members']:
        if m['class'] != 'reuse':
            continue
        sites = m.get('surviving_sites')
        if not sites:
            errors.append('顶包名 %s/%s 缺存活格核对结论 ⇒ 中止写盘（resource-naming.md §7.7）'
                          % (m['archive'], m['name']))
            continue
        for st in sites:
            if st.get('decision') != 'rewrite':
                continue
            tgt = st['rewrite_to']
            reuse_rewrites.append({'script': st['script'], 'offset': int(st['name_offset']),
                                   'slot': int(st['slot']), 'from': m['name'], 'to': tgt})
            ext = os.path.splitext(tgt)[1].lower()
            classify(tgt, {'.png': 'png', '.pna': 'pna', '.ogg': 'voice'}.get(ext, 'png'))
    # ── 闸：等长 1:1 块的内容面存疑对不得被「1:1 承载」掉 ──
    # 承载图的 1:1 判据只看 token 骨架（行数相等即判 1:1）；两侧语音号不一致者已由
    # `script/build/build_carrier_map.py` 标 `content_suspect`（见 doc/lessons-learned.md §14／§16）。
    # 这些对（两侧语音号都存在且不同 ⇒ 非同一行）**必须走还原**（drop/rebind，原版行进产物）。
    # 民汉覆盖（`text_override`）只挂在 verified 保留格上，对 content_suspect 对无效（见
    # doc/restoration-targets.md：build_host_plan 对「保留格 + text_override 但槽在
    # content_suspect」直接断言失败）⇒ 它**不能**作为存疑对的消化手段。既不在 drops、
    # 也不可能是合法 text_override ⇒ 还原缺口，中止写盘，交判读定形态。
    carried = []
    for s, e in v5lib.carrier().items():
        host = plans['hosts'].get(s)
        if not host or host.get('kind') != 'host':
            continue
        drp = set(host['plan']['drops'])
        for b in e['blocks']:
            for p in (b.get('content_suspect') or []):
                if p['steam_slot'] in drp:
                    continue
                carried.append('%s o%d/s%d' % (s, p['orig_row'], p['steam_slot']))
    if carried:
        errors.append('等长 1:1 块内容存疑且被直接承载 %d 对（原版行未进产物）⇒ 中止写盘，'
                      '交判读定形态；例：%s' % (len(carried), ', '.join(carried[:6])))

    plans['reuse_rewrites'] = reuse_rewrites
    plans['resources'] = resource_plan
    plans['gates'] = gates

    with open(OUT_JSON, 'w', encoding='utf-8', newline='\n') as f:
        json.dump(plans, f, ensure_ascii=False, indent=1)
        f.write('\n')

    md = ['# restore_plan 报表', '',
          '- A-1：%d；宿主：%d；跳转恢复：%d' % (len(plans['A1']), len(plans['hosts']), len(plans['jumps'])),
          '- 资源：复制 %d、覆盖 %d、Steam 已有 %d' % (len(resource_plan['copy']),
                                                    len(resource_plan['overwrite']),
                                                    resource_plan['have']),
          '- 覆盖构成：图像 %d（判定表 censor_map）、语音 %d（判定表 voice_conflict_map，'
          '其中噪声 keep %d）'
          % (sum(1 for x in resource_plan['overwrite'] if x['kind'] != 'voice'),
             sum(1 for x in resource_plan['overwrite'] if x['kind'] == 'voice'),
             sum(1 for m in vmap['members'] if m['action'] == 'keep')),
          '- 顶包调用点改写：%d 处' % len(reuse_rewrites),
          '- 闸：errors %d' % len(errors), '']
    if errors:
        md += ['## errors', ''] + ['- ' + e for e in errors] + ['']
    with open(OUT_MD, 'w', encoding='utf-8', newline='\n') as f:
        f.write('\n'.join(md))
    print('plan: A1 %d / hosts %d / jumps %d ; resources copy %d overwrite %d have %d ; '
          'reuse_rewrites %d ; errors %d'
          % (len(plans['A1']), len(plans['hosts']), len(plans['jumps']),
             len(resource_plan['copy']), len(resource_plan['overwrite']),
             resource_plan['have'], len(reuse_rewrites), len(errors)))
    for e in errors[:15]:
        print('  ERR', e.encode('ascii', 'replace').decode())
    sys.exit(1 if errors else 0)


def conv_script(x):
    return x


if __name__ == '__main__':
    main()
