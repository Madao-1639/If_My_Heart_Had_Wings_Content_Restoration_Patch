# -*- coding: utf-8 -*-
"""补丁构建器（管线步 4）：从 `backup/` 起底，产出 `asset/` 单棵输出树。

归档接线（route §1 + afterstory-mechanics §10，合并方式 = §2 硬纪律 4 的①）：
- 本写盘器**单趟**写全部共享归档：`Rio.arc`（A-1 + A-2/A-3 + G4 start.ws2 + 顶包调用点改写）、
  `zh-CN/Rio.arc`（宿主合并 `.lng` + A-1 `.lng` 现做 + G5 SL lng + G10 NameTable）、
  `SE.arc`（本体 9 + L4 的 3 = 需求并集，全部取自原版）、
  VOICE/CHIP*/GRAPHIC（补缺 + **按覆盖名单整名替换同名成员**）。
- L4 独有交付从 `script/build/build_l4.py` 的产物树收割：`Script.arc`（G1/G2/G6）、
  `PVOICE.arc`/`PCHIP.arc`（G7）、裸 `RIO/SL_*.ws2`（G3）。
- **交付面只含有差异的归档**：与 backup 无差异者（BGM/SysVoice/SysGraphic/Effect/Chip1）
  **不写入 `asset/`**，安装期由玩家原档直接提供。**「有差异」含同名成员只换内容**：
  覆盖不新增成员，只看字节是否等于原版（route §1）。

硬纪律：backup 只读；同一归档只一趟写盘；可复现（同输入两次构建逐字节一致）；
覆盖**只认判定表的 `overwrite` 子集**、逐名对齐替换次数（route §4 写盘器硬要求）。
"""
import collections
import hashlib
import json
import os
import struct
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
from tool import arcbuild, ws2, lng, ws2dis  # noqa: E402
from tool import writer  # noqa: E402
from tool import paths  # noqa: E402
from tool.ws2conv import load_orig_formats, convert_script  # noqa: E402

ASSET = os.path.join(ROOT, 'asset')
L4_TREE = os.path.join(ROOT, 'tmp', '_l4', 'asset')
PLAN = os.path.join(ROOT, 'resource', 'restore_plan.json')
STEAM = paths.STEAM
ORIG = None

ADD_ARCHIVES = ['VOICE.arc', 'Chip1.arc', 'CHIP2.arc', 'CHIP3.arc', 'CHIP4.arc',
                'CHIP5.arc', 'CHIP6.arc', 'GRAPHIC.arc', 'SE.arc']


def sha1(path):
    h = hashlib.sha1()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def read_members(path):
    return {nb.decode('utf-16le', 'replace'): d for nb, d in arcbuild.read_raw(path)}


def steam_slot_ids(dec):
    """Steam 解码流里逐 `14` 的 id 字段（按出现序）。`14` 的操作数首 2 字节即 id。"""
    instrs, ok = ws2dis.disassemble(dec)
    assert ok, 'steam disassemble not self-consistent'
    return [struct.unpack_from('<H', ops, 0)[0] for _off, op, _sz, ops in instrs if op == 0x14]


def display_names_of_slot(dec, slot):
    """产物某槽（14 序）格内的 0x33／0x34 显示名列表。"""
    instrs, ok = ws2dis.disassemble(dec)
    assert ok
    cur, found = -1, []
    for _off, op, _sz, ops in instrs:
        if op == 0x14:
            cur += 1
        if op in (0x33, 0x34) and cur == slot:
            parts = ops.split(b'\x00')
            if len(parts) > 1:
                found.append(parts[1].decode('cp932', 'replace').upper())
    return found


def main():
    orig_dir = os.environ.get('IFMH_ORIG_DIR') or ''
    if not orig_dir or not os.path.isdir(orig_dir):
        sys.exit('需要原版目录：设环境变量 IFMH_ORIG_DIR 或让 build_l4/convert 的口径生效')
    globals()['ORIG'] = orig_dir
    plan = json.load(open(PLAN, encoding='utf-8'))
    ofmt = load_orig_formats(orig_dir)

    # ── 0. L4 产物（backup 起底、幂等；其共享归档输出被本写盘器顶掉）──
    env = dict(os.environ, IFMH_ORIG_DIR=orig_dir)
    subprocess.run([sys.executable, os.path.join(ROOT, 'script', 'build', 'build_l4.py')],
                   check=True, env=env, cwd=ROOT,
                   stdout=subprocess.DEVNULL)
    l4_rio = read_members(os.path.join(L4_TREE, 'Rio.arc'))
    l4_zh = read_members(os.path.join(L4_TREE, 'zh-CN', 'Rio.arc'))

    os.makedirs(ASSET, exist_ok=True)
    report = []

    # ── 1. Rio.arc ──
    rio = read_members(os.path.join(STEAM, 'Rio.arc'))
    for script, pl in plan['A1'].items():
        name = script + '.ws2'
        conv = convert_script(read_orig_raw(script), orig_dir)
        if pl.get('names'):
            dec = writer.apply_names(ws2.decode(conv),
                                     {k.encode('ascii'): v.encode('ascii')
                                      for k, v in pl['names'].items()})
            conv = ws2.encode(dec)
        rio[name] = conv
        report.append('Rio +A1 %s (%dB)' % (script, len(conv)))
    for script, old, new in plan['jumps']:
        name = script + '.ws2'
        dec = ws2.decode(rio[name])
        tok_old = b'\x07' + old.encode('ascii') + b'\x00'
        tok_new = b'\x07' + new.encode('ascii') + b'\x00'
        assert dec.count(tok_old) == 1, '%s: 尾跳 %s 出现 %d 次' % (script, old, dec.count(tok_old))
        rio[name] = ws2.encode(dec.replace(tok_old, tok_new))
        report.append('Rio jump %s: %s -> %s' % (script, old, new))
    # 顶包（class=reuse）存活格调用点改写：在**重建前**的 Steam 解码流上按调用点
    # 做**等长** NUL 定界精确替换（长度不变 ⇒ 不影响任何偏移；禁全局替换——同一名在
    # 不同宿主/段落里可能指两侧不同图）。结论来自判定表成员的 `surviving_sites`，
    # 见 doc/resource-naming.md §3／§6／§7.7。
    for rw in plan.get('reuse_rewrites', []):
        name = rw['script'] + '.ws2'
        dec = ws2.decode(rio[name])
        off = int(rw['offset'])
        old = rw['from'].encode('ascii')
        new = rw['to'].encode('ascii')
        assert len(old) == len(new), '改写长度不一致 %s -> %s' % (rw['from'], rw['to'])
        assert dec[off:off + len(old)].upper() == old.upper(), \
            '%s: 调用点 %#x 处的名字不是 %s（实为 %r）' % (
                rw['script'], off, rw['from'], dec[off:off + len(old)])
        rio[name] = ws2.encode(dec[:off] + new + dec[off + len(old):])
        report.append('Rio reuse-rewrite %s @%#x: %s -> %s'
                      % (rw['script'], off, rw['from'], rw['to']))
    # 改写点在**产物槽序**里的位置（rebuild 会删被删格的 14/15 ⇒ 产物槽序 ≠ Steam 原槽序，
    # 须经 `slot_sources` 换算）。这里记下改写点的 Steam 侧 `14.id` 与各宿主的槽序来源表。
    reuse_sid, slot_sources_of = {}, {}
    for script, pl in plan['hosts'].items():
        if pl['kind'] == 'skip':
            continue
        name = script + '.ws2'
        pl['plan']['script'] = script
        pre = ws2.decode(rio[name])
        for rw in plan.get('reuse_rewrites', []):
            if rw['script'] == script:
                reuse_sid[script] = steam_slot_ids(pre)[rw['slot']]
        res = writer.rebuild_host(pre, read_orig_dec(script), pl['plan'], ofmt)
        assert res['ok'] and res['fix_bad'] == 0, \
            '%s: rebuild fail ok=%s fix_bad=%d' % (script, res['ok'], res['fix_bad'])
        rio[name] = res['raw']
        slot_sources_of[script] = res['slot_sources']
        report.append('Rio host %s: slots %d (drops %d, rows +%d)'
                      % (script, res['n_slots'], len(pl['plan']['drops']), pl['n_insert_rows']))
    if 'start.ws2' in l4_rio:
        rio['start.ws2'] = l4_rio['start.ws2']          # G4（SetFlag 1000=1）
        report.append('Rio start.ws2 <- L4 (G4)')
    out = os.path.join(ASSET, 'Rio.arc')
    arcbuild.write_arc([(k.encode('utf-16le'), v) for k, v in rio.items()], out)
    arcbuild.verify(out, expect_count=len(rio))
    report.append('Rio.arc: %d members' % len(rio))

    # 回读校验：顶包调用点改写必须落到产物（route §4 写盘器硬要求）
    if plan.get('reuse_rewrites'):
        back = read_members(out)
        for rw in plan['reuse_rewrites']:
            dec2 = ws2.decode(back[rw['script'] + '.ws2'])
            srcs = slot_sources_of.get(rw['script'])
            assert srcs, '%s: 缺 slot_sources，无法换算产物槽序' % rw['script']
            sid = reuse_sid[rw['script']]
            idxs = [i for i, (k, v) in enumerate(srcs) if k == 'steam' and v == sid]
            assert len(idxs) == 1, \
                '%s: 改写点（Steam id %d）在产物槽序里不唯一 %r' % (rw['script'], sid, idxs)
            found = display_names_of_slot(dec2, idxs[0])
            assert rw['to'].upper() in found, \
                '%s: 顶包调用点改写未落到产物槽 %d（实为 %r）' % (rw['script'], idxs[0], found)
            report.append('回读 reuse-rewrite %s 产物槽 %d: %s -> %s'
                          % (rw['script'], idxs[0], rw['from'], rw['to']))

    # ── 2. zh-CN/Rio.arc ──
    zh = read_members(os.path.join(STEAM, 'zh-CN', 'Rio.arc'))
    for script, pl in plan['A1'].items():
        zh[script + '.lng'] = lng.encode_lng(pl['texts'], key=lng.KEY_STEAM_ZHCN)
        report.append('zh +A1 %s.lng (%d slots)' % (script, len(pl['texts'])))
    for script, pl in plan['hosts'].items():
        if pl['kind'] == 'skip':
            continue
        zh[script + '.lng'] = lng.encode_lng(pl['slot_texts'], key=lng.KEY_STEAM_ZHCN)
        report.append('zh host %s.lng (%d slots)' % (script, len(pl['slot_texts'])))
    for name, d in l4_zh.items():
        if name.lower().endswith('.lng') and name.upper().startswith('SL_'):
            zh[name] = d                                   # G5
            report.append('zh +%s' % name)
    if 'NameTable.txt' in l4_zh:
        zh['NameTable.txt'] = l4_zh['NameTable.txt']       # G10（唯一合并出口）
        report.append('zh NameTable.txt <- L4 (G10)')
    out = os.path.join(ASSET, 'zh-CN', 'Rio.arc')
    os.makedirs(os.path.dirname(out), exist_ok=True)
    arcbuild.write_arc([(k.encode('utf-16le'), v) for k, v in zh.items()], out)
    arcbuild.verify(out, expect_count=len(zh))
    report.append('zh-CN/Rio.arc: %d members' % len(zh))

    # ── 3. 资源归档（补缺 + 按覆盖名单整名替换）──
    # 需求并集按归档分组；G9：33 张后日谈分层立绘 .pna 无条件并入 GRAPHIC.arc
    sys.path.insert(0, os.path.join(ROOT, 'script', 'build'))
    from build_l4 import SL_PNA, EXTRA_SE  # noqa: E402
    need = collections.defaultdict(dict)         # arch -> {low_name: None}（Steam 缺 ⇒ 补入，继承原名）
    overwrite = collections.defaultdict(dict)    # arch -> {steam_low: (steam_name, orig_name)}
    for se in EXTRA_SE:                          # G8：L4 独有 SE 并入主线 SE 趟
        need['SE.arc'].setdefault(se.lower(), None)
    for e in plan['resources']['copy']:
        need[e['archive']][e['orig'].lower()] = None
    for e in plan['resources'].get('overwrite', []):
        overwrite[e['archive']][e['name'].lower()] = (e['name'], e['orig_name'])
    for pna in SL_PNA:
        need['GRAPHIC.arc'].setdefault(pna.lower(), None)

    import shutil
    ow_done = 0
    for arch in ADD_ARCHIVES:
        members = read_members(os.path.join(STEAM, arch))
        want = need.get(arch, {})
        ow = overwrite.get(arch, {})
        assert not (set(want) & set(ow)), \
            '%s: 同名成员同时进了补入与覆盖名单 %r' % (arch, sorted(set(want) & set(ow))[:5])
        # 原版侧要取的成员 = 补入名单 ∪ 覆盖名单的源名
        want_orig = set(want) | {o.lower() for _, o in ow.values()}
        got = {}
        if want_orig:
            for nb, d in arcbuild.read_raw(os.path.join(ORIG, arch)):
                n = nb.decode('utf-16le', 'replace')
                low = n.lower()
                if low in want_orig and low not in got:
                    got[low] = (n, d)
        missing = [w for w in want_orig if w not in got]
        if missing and arch == 'SE.arc' and os.path.exists(os.path.join(ORIG, 'PSE.arc')):
            for nb, d in arcbuild.read_raw(os.path.join(ORIG, 'PSE.arc')):   # G8：L4 SE 源 = PSE
                n = nb.decode('utf-16le', 'replace')
                low = n.lower()
                if low in missing and low not in got:
                    got[low] = (n, d)
        missing = [w for w in want_orig if w not in got]
        assert not missing, '%s: 原版缺成员 %d 个，如 %r' % (arch, len(missing), missing[:5])
        have = {k.lower(): k for k in members}       # 小写名 → Steam 侧实际成员名
        added = 0
        for low, (n, d) in got.items():
            if low not in want:
                continue
            if low in have:
                continue          # Steam 已有同名成员（可能仅大小写不同），补入即重名成员
            members[n] = d
            added += 1
        # 覆盖：Steam 成员名与归档表位置不变，只换内容（写盘器硬要求，route §4）
        replaced = 0
        for low, (sname, oname) in sorted(ow.items()):
            actual = have.get(low)
            assert actual is not None, '%s: 覆盖名单成员 %s 不在 Steam 归档内' % (arch, sname)
            src = got.get(oname.lower())
            assert src is not None, '%s: 覆盖源 %s 不在原版归档内' % (arch, oname)
            members[actual] = src[1]
            replaced += 1
        assert replaced == len(ow), '%s: 覆盖数 %d != 名单 %d' % (arch, replaced, len(ow))
        ow_done += replaced
        out = os.path.join(ASSET, arch)
        if added or replaced:
            arcbuild.write_arc([(k.encode('utf-16le'), v) for k, v in members.items()], out)
            arcbuild.verify(out, expect_count=len(members))
            report.append('%s: +%d 补入, %d 覆盖' % (arch, added, replaced))
        else:
            report.append('%s: 与 backup 无差异，不交付' % arch)
    assert ow_done == len(plan['resources'].get('overwrite', [])), \
        '覆盖子集未逐名落地：写盘 %d != 名单 %d（route §4 硬要求）' % (
            ow_done, len(plan['resources'].get('overwrite', [])))
    report.append('覆盖落地: %d 名（名单 %d 名）'
                  % (ow_done, len(plan['resources'].get('overwrite', []))))

    # ── 4. L4 独有交付 ──
    shutil.copyfile(os.path.join(L4_TREE, 'Script.arc'), os.path.join(ASSET, 'Script.arc'))
    for arch in ('PVOICE.arc', 'PCHIP.arc'):
        p = os.path.join(L4_TREE, arch)
        if os.path.exists(p):
            shutil.copyfile(p, os.path.join(ASSET, arch))
    rio_dir = os.path.join(ASSET, 'RIO')
    os.makedirs(rio_dir, exist_ok=True)
    for f in os.listdir(os.path.join(L4_TREE, 'RIO')):
        shutil.copyfile(os.path.join(L4_TREE, 'RIO', f), os.path.join(rio_dir, f))
    report.append('Script.arc / PVOICE / PCHIP / RIO <- L4')

    with open(os.path.join(ROOT, 'tmp', 'build_patch_report.txt'), 'w', encoding='utf-8') as f:
        f.write('\n'.join(report))
    print('build_patch done: %d report lines' % len(report))


def read_orig_raw(script):
    for nb, d in arcbuild.read_raw(os.path.join(ORIG, 'Rio.arc')):
        n = nb.decode('utf-16le', 'replace')
        if n.lower() == script.lower() + '.ws2':
            return d
    raise KeyError(script)


def read_orig_dec(script):
    return ws2.decode(read_orig_raw(script))


def find_orig_member(name, expect_arch):
    """在原版归档中定位成员（expect_arch 优先，否则全归档索引）。"""
    p = os.path.join(ORIG, expect_arch)
    for nb, d in arcbuild.read_raw(p):
        n = nb.decode('utf-16le', 'replace')
        if n.lower() == name.lower():
            return d
    for arch in ADD_ARCHIVES:
        if arch == expect_arch:
            continue
        for nb, d in arcbuild.read_raw(os.path.join(ORIG, arch)):
            n = nb.decode('utf-16le', 'replace')
            if n.lower() == name.lower():
                return d
    raise KeyError('%s not found in orig archives (%s)' % (name, expect_arch))


if __name__ == '__main__':
    main()
