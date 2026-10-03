# -*- coding: utf-8 -*-
"""补丁构建器（管线步 4）：从 `backup/` 起底，产出 `asset/` 单棵输出树。

归档接线（route §1 + afterstory-mechanics §10，合并方式 = §2 硬纪律 4 的①）：
- 本写盘器**单趟**写全部共享归档：`Rio.arc`（A-1 + A-2/A-3 + G4 start.ws2）、
  `zh-CN/Rio.arc`（宿主合并 `.lng` + A-1 `.lng` 现做 + G5 SL lng + G10 NameTable）、
  `SE.arc`（本体 9 + L4 的 3 = 需求并集，全部取自原版）、VOICE/CHIP*/GRAPHIC（补缺 + 改名）。
- L4 独有交付从 `script/build_l4.py` 的产物树收割：`Script.arc`（G1/G2/G6）、
  `PVOICE.arc`/`PCHIP.arc`（G7）、裸 `RIO/SL_*.ws2`（G3）。
- **交付面只含有差异的归档**：与 backup 无差异者（BGM/SysVoice/SysGraphic/Effect/Chip1）
  **不写入 `asset/`**，安装期由玩家原档直接提供。

硬纪律：backup 只读；同一归档只一趟写盘；可复现（同输入两次构建逐字节一致）。
"""
import collections
import hashlib
import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
    sys.path.insert(0, os.path.join(ROOT, 'tmp', 'restdiff'))
from tool import arcbuild, ws2, lng  # noqa: E402
from tool import writer  # noqa: E402
from tool.ws2conv import load_orig_formats, convert_script  # noqa: E402
import paths  # noqa: E402

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


def main():
    orig_dir = os.environ.get('IFMH_ORIG_DIR') or ''
    if not orig_dir or not os.path.isdir(orig_dir):
        sys.exit('需要原版目录：设环境变量 IFMH_ORIG_DIR 或让 build_l4/convert 的口径生效')
    globals()['ORIG'] = orig_dir
    plan = json.load(open(PLAN, encoding='utf-8'))
    ofmt = load_orig_formats(orig_dir)

    # ── 0. L4 产物（backup 起底、幂等；其共享归档输出被本写盘器顶掉）──
    env = dict(os.environ, IFMH_ORIG_DIR=orig_dir)
    subprocess.run([sys.executable, os.path.join(ROOT, 'script', 'build_l4.py')],
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
    for script, pl in plan['hosts'].items():
        if pl['kind'] == 'skip':
            continue
        name = script + '.ws2'
        pl['plan']['script'] = script
        res = writer.rebuild_host(ws2.decode(rio[name]), read_orig_dec(script), pl['plan'], ofmt)
        assert res['ok'] and res['fix_bad'] == 0, \
            '%s: rebuild fail ok=%s fix_bad=%d' % (script, res['ok'], res['fix_bad'])
        rio[name] = res['raw']
        report.append('Rio host %s: slots %d (drops %d, rows +%d)'
                      % (script, res['n_slots'], len(pl['plan']['drops']), pl['n_insert_rows']))
    if 'start.ws2' in l4_rio:
        rio['start.ws2'] = l4_rio['start.ws2']          # G4（SetFlag 1000=1）
        report.append('Rio start.ws2 <- L4 (G4)')
    out = os.path.join(ASSET, 'Rio.arc')
    arcbuild.write_arc([(k.encode('utf-16le'), v) for k, v in rio.items()], out)
    arcbuild.verify(out, expect_count=len(rio))
    report.append('Rio.arc: %d members' % len(rio))

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

    # ── 3. 资源归档（补缺 + 改名隔离）──
    # 需求并集按归档分组；G9：33 张后日谈分层立绘 .pna 无条件并入 GRAPHIC.arc
    sys.path.insert(0, os.path.join(ROOT, 'script'))
    from build_l4 import SL_PNA, EXTRA_SE  # noqa: E402
    need = collections.defaultdict(dict)     # arch -> {low_name: patch_name or None}
    for se in EXTRA_SE:                      # G8：L4 独有 SE 并入主线 SE 趟
        if 'SE.arc' not in need or se.lower() not in need['SE.arc']:
            need['SE.arc'][se.lower()] = None
    for e in plan['resources']['copy']:
        need[e['archive']][e['orig'].lower()] = None
    for e in plan['resources']['rename']:
        need[e['archive']][e['orig'].lower()] = e['patch']
    for pna in SL_PNA:
        if 'GRAPHIC.arc' not in need or pna.lower() not in need['GRAPHIC.arc']:
            need['GRAPHIC.arc'][pna.lower()] = None

    import shutil
    for arch in ADD_ARCHIVES:
        members = read_members(os.path.join(STEAM, arch))
        want = need.get(arch, {})
        got = {}
        if want:
            for nb, d in arcbuild.read_raw(os.path.join(ORIG, arch)):
                n = nb.decode('utf-16le', 'replace')
                low = n.lower()
                if low in want and low not in got:
                    got[low] = (n, d)
        missing = [w for w in want if w not in got]
        if missing and arch == 'SE.arc' and os.path.exists(os.path.join(ORIG, 'PSE.arc')):
            for nb, d in arcbuild.read_raw(os.path.join(ORIG, 'PSE.arc')):   # G8：L4 SE 源 = PSE
                n = nb.decode('utf-16le', 'replace')
                low = n.lower()
                if low in missing and low not in got:
                    got[low] = (n, d)
        missing = [w for w in want if w not in got]
        assert not missing, '%s: 原版缺成员 %d 个，如 %r' % (arch, len(missing), missing[:5])
        have = {k.lower() for k in members}
        added = 0
        for low, (n, d) in got.items():
            patch = want[low]
            if patch:
                assert patch.lower() not in have, \
                    '%s: 改名目标 %s 与 Steam 原成员重名（违反零破坏性）' % (arch, patch)
                members[patch] = d
            elif low in have:
                continue          # Steam 已有同名成员（可能仅大小写不同），补入即重名成员
            else:
                members[n] = d
            added += 1
        out = os.path.join(ASSET, arch)
        if added:
            arcbuild.write_arc([(k.encode('utf-16le'), v) for k, v in members.items()], out)
            arcbuild.verify(out, expect_count=len(members))
            report.append('%s: +%d' % (arch, added))
        else:
            report.append('%s: 与 backup 无差异，不交付' % arch)

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
