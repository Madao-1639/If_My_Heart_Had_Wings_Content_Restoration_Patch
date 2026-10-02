# -*- coding: utf-8 -*-
"""插入计划器（管线步 3）：判读台账 + 承载图 + 改名表 + 双语语料 → resource/restore_plan.json。

产物（每脚本）：
  A-1   kind=whole  —— 整脚本经 ws2conv.convert_script 转换；槽位文本 = fan_cn 按原版 idx 1:1。
  宿主  kind=host   —— drops/inserts/external + slot_sources + slot_texts（最终槽位序：
                          保留格 = 官方 .lng 按旧 idx 直索引（CO1_020 空洞天然跳过）；
                          插入格 = resource/fan_cn 按原版行 idx）。
  跳转  kind=jump   —— 5 处入口尾跳改回原版目标（等长名字节替换）。

资源需求：扫还原区间（A-1 全脚本）的 0x28(0x2e 语音体/SE)、0x1e(BGM)、0x33(PNG)、
0x34(PNA/PNG) 引用 → 三分类：Steam 已有（跳过）/ 冲突且被引用（走 rename_map）/
Steam 缺失（从原版对应归档复制，归档归属按「原版成员名 → 归档」实测索引）。

闸（只看表，任一不过即退出 1）：台账全覆盖 / 插入锚不落被删格 / 锚内行序单调 /
插入块零 0f 且 14 数=行数 / 跨块跳转全解析 / 槽位文本无缺失 / 资源三分类无遗漏。
"""
import collections
import glob
import json
import os
import struct
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
    sys.path.insert(0, os.path.join(ROOT, 'tmp', 'restdiff'))
from tool import arcbuild, ws2, ws2dis, lng, scriptext  # noqa: E402
from tool import v5lib  # noqa: E402
from tool.ws2conv import load_orig_formats, parse as conv_parse, convert_script, REBASE_OPS  # noqa: E402
from tool import writer  # noqa: E402
import paths  # noqa: E402

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
            return lng.parse_lng(d, key=lng.KEY_STEAM_ZHCN)
    return None


def fan_texts(script):
    p = os.path.join(ROOT, 'resource', 'fan_cn', script + '.json')
    if not os.path.exists(p):
        return None
    with open(p, encoding='utf-8') as f:
        d = json.load(f)
    texts = d['texts'] if isinstance(d, dict) and 'texts' in d else d
    return [e.get('text_with_name') or e['text'] if isinstance(e, dict) else e for e in texts]


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
            chan = parts[0].decode('ascii', 'replace').upper()
            fname = parts[1].decode('ascii', 'replace').upper()
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
    row_slot = carrier_row_slot(script)
    for e in blocks:
        for c in e.get('cells', []):
            if c['action'] == 'rebind':
                drops.append(c['slot'])
                inserts.append((c['slot'], c['bind_orig_row'], c['bind_orig_row']))
            elif c['action'] == 'drop':
                drops.append(c['slot'])
        for ins in e.get('inserts', []):
            a = ins['after_slot']
            a = -1 if a == -1 else a
            inserts.append((a, ins['orig_rows'][0], ins['orig_rows'][1]))
    drops = sorted(set(drops))
    if not drops and not inserts:
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
        i1 = o14[r1 + 1] if r1 + 1 < len(o14) else len(oinstrs)
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
            'external': ext}
    res = writer.rebuild_host(steam_dec, orig_dec, plan, ofmt)
    assert res['ok'] and res['fix_bad'] == 0, \
        '%s: rebuild fail ok=%s fix_bad=%d n14=%d n_slots=%d pool=%d' % (
            script, res['ok'], res['fix_bad'], res['n14'], res['n_slots'], res['pool'])

    # 槽位文本
    off_lng = official_lng(script)
    fan = fan_texts(script)
    slot_texts = []
    for kind, key in res['slot_sources']:
        if kind == 'steam':
            assert off_lng is not None and 0 <= key < len(off_lng), \
                '%s: 保留槽 idx %d 无官方条目' % (script, key)
            slot_texts.append(off_lng[key])
        else:
            assert fan is not None and 0 <= key < len(fan), \
                '%s: 插入行 %d 无民汉文本' % (script, key)
            slot_texts.append(fan[key])

    # 资源需求
    spans = []
    for a, r0, r1 in ins_ranges:
        i0 = o14[r0 - 1] + 1 if r0 > 0 else 0
        i1 = o14[r1 + 1] if r1 + 1 < len(o14) else len(oinstrs)
        spans.append((i0, i1))
    need = scan_resources(orig_dec, spans, ofmt)
    names = {n.lower(): ren[n.lower()] for kinds in need.values() for n in kinds
             if n.lower() in ren}
    gates['slots_%s' % script] = len(slot_texts)
    plan['names'] = names
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
    gates = {}
    errors = []
    plans = {'A1': {}, 'hosts': {}, 'jumps': [list(j) for j in JUMP_REVERTS]}
    rename = json.load(open(os.path.join(ROOT, 'resource', 'rename_map.json'), encoding='utf-8'))
    ren = {}
    for k in ('voice', 'sprite', 'mos', 'est'):
        for e in rename.get(k, []):
            ren[e['orig'].lower()] = e['patch']

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

    # 资源三分类
    steam_names = {}
    for arch in ('VOICE.arc', 'CHIP2.arc', 'CHIP3.arc', 'CHIP4.arc', 'CHIP5.arc',
                 'CHIP6.arc', 'GRAPHIC.arc', 'SE.arc', 'BGM.arc'):
        steam_names[arch] = arc_names(os.path.join(paths.STEAM, arch))
    orig_index = {}
    for arch in ('VOICE.arc', 'Chip1.arc', 'CHIP2.arc', 'CHIP3.arc', 'CHIP4.arc',
                 'CHIP5.arc', 'CHIP6.arc', 'GRAPHIC.arc', 'SE.arc', 'BGM.arc'):
        for low in arc_names(os.path.join(paths.orig_dir(), arch)):
            orig_index.setdefault(low, arch)
    resource_plan = {'copy': [], 'rename': [], 'have': 0}
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
    for kind, names in sorted(allneed.items()):
        for n in sorted(names):
            low = n.lower()
            if low in seen:
                continue
            seen.add(low)
            # 归档归属：语音/SE/BGM 固定；图形按「原版索引」
            if arch_of[kind]:
                arch = arch_of[kind]
            else:
                arch = orig_index.get(low)
                if arch is None:
                    errors.append('资源 %s（%s）原版全归档找不到归属' % (n, kind))
                    continue
            in_steam = low in steam_names.get(arch, {})
            if low in ren:
                resource_plan['rename'].append({'kind': kind, 'archive': arch,
                                                'orig': n, 'patch': ren[low]})
            elif in_steam:
                resource_plan['have'] += 1
            else:
                if low in {e['name'].lower() for e in rename.get('unused_conflicts', [])}:
                    errors.append('资源 %s 是未引用冲突但被还原内容引用——rename_map 口径矛盾' % n)
                    continue
                resource_plan['copy'].append({'kind': kind, 'archive': arch, 'orig': n})
    plans['resources'] = resource_plan
    plans['gates'] = gates

    with open(OUT_JSON, 'w', encoding='utf-8', newline='\n') as f:
        json.dump(plans, f, ensure_ascii=False, indent=1)
        f.write('\n')

    md = ['# restore_plan 报表', '',
          '- A-1：%d；宿主：%d；跳转恢复：%d' % (len(plans['A1']), len(plans['hosts']), len(plans['jumps'])),
          '- 资源：复制 %d、改名 %d、Steam 已有 %d' % (len(resource_plan['copy']),
                                                    len(resource_plan['rename']), resource_plan['have']),
          '- 闸：errors %d' % len(errors), '']
    if errors:
        md += ['## errors', ''] + ['- ' + e for e in errors] + ['']
    with open(OUT_MD, 'w', encoding='utf-8', newline='\n') as f:
        f.write('\n'.join(md))
    print('plan: A1 %d / hosts %d / jumps %d ; resources copy %d rename %d have %d ; errors %d'
          % (len(plans['A1']), len(plans['hosts']), len(plans['jumps']),
             len(resource_plan['copy']), len(resource_plan['rename']),
             resource_plan['have'], len(errors)))
    for e in errors[:15]:
        print('  ERR', e.encode('ascii', 'replace').decode())
    sys.exit(1 if errors else 0)


def conv_script(x):
    return x


if __name__ == '__main__':
    main()
