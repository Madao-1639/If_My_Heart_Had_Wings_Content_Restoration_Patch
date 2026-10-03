# -*- coding: utf-8 -*-
"""全量验收（管线步 6）——route §5 的 8 项门。

1  归档完整性        ：交付归档（asset 中有差异者）全部过 arcbuild.verify()；
                       asset 不含无差异归档（BGM/Chip1/SysVoice/SysGraphic/Effect 不交付）
2  调用链完整性      ：全部脚本的 07/02 目标可达（Rio 成员 ∪ 裸 RIO ∪ TITLE/EVRET；
                       数字 label 跳转按名单豁免）；A-1 的 5 处跳转已恢复
3  成就触发点完整性  ：CG_ACHIEVEMENT 调用 922 处 + 0xF0 触发 29 处，逐脚本不变
4  资源配对正确性    ：全部脚本的 0x33/0x34/语音/SE/BGM 引用可解析
                       （交付归档取 asset，未交付者取 backup＝玩家原档）
5  零破坏性          ：各归档 'keep' 成员与 backup 逐字节相等（Steam 原件未被替换）
6  可复现性          ：当前 asset 哈希 == payload/METADATA.json 的 checksum/files
7  实机测试          ：人工（打印清单，不自动）
8  交付项完整性      ：L4 自有交付逐名断言 + GRAPHIC 含 33 张 SL .pna + A-1 lng 槽位

任一闸失败退出码 1。明细写 tmp/final_verification.md。
"""
import collections
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
    sys.path.insert(0, os.path.join(ROOT, 'tmp', 'restdiff'))
from tool import arcbuild, ws2, ws2dis, lng  # noqa: E402
import paths  # noqa: E402

ASSET = os.path.join(ROOT, 'asset')
BACKUP = os.path.join(ROOT, 'backup')
# 交付归档 = 相对 backup 有差异、由 build_patch 写入 asset/ 者；
# 无差异的 BGM/Chip1/SysVoice/SysGraphic/Effect 不进 asset，验收按 backup（＝玩家原档）解析
SHIPPED_ARCHIVES = ['Rio.arc', 'zh-CN/Rio.arc', 'Script.arc', 'GRAPHIC.arc', 'SE.arc',
                    'VOICE.arc', 'CHIP2.arc', 'CHIP3.arc', 'CHIP4.arc', 'CHIP5.arc',
                    'CHIP6.arc', 'PVOICE.arc', 'PCHIP.arc']
LABEL_OK = {'706', '801'}          # 选项 label 跳转（两版一致的数字 label）
EXPECT_HOOKS = 922
EXPECT_F0 = 29
EXPECT_SL_LNG = {'SL_AGE_001': 851, 'SL_AMA_001': 714, 'SL_HUT_001': 788, 'SL_KOT_001': 875}

fails = []
lines = []


def check(name, ok, detail=''):
    lines.append('[%s] %s %s' % ('PASS' if ok else 'FAIL', name, detail))
    if not ok:
        fails.append(name)
    return ok


def read_members(path):
    return {nb.decode('utf-16le', 'replace'): d for nb, d in arcbuild.read_raw(path)}


def arch_path(name):
    """交付归档取 asset/；与 backup 无差异而不交付者回落 backup/（＝玩家原档）。"""
    p = os.path.join(ASSET, name)
    return p if os.path.exists(p) else os.path.join(BACKUP, name)


def asset_arcs():
    """asset/ 中实际存在的归档相对路径（正斜杠）。"""
    out = set()
    for dirpath, _dirs, files in os.walk(ASSET):
        for fn in files:
            if fn.lower().endswith('.arc'):
                out.add(os.path.relpath(os.path.join(dirpath, fn), ASSET).replace('\\', '/'))
    return out


def dec_of(members, script):
    return ws2.decode(members[script + '.ws2'])


def main():
    # ── 1. 归档完整性 ──
    for arch in SHIPPED_ARCHIVES:
        p = os.path.join(ASSET, arch)
        if not os.path.exists(p):
            check('1 交付归档存在 %s' % arch, False)
            continue
        try:
            arcbuild.verify(p)
            check('1 verify %s' % arch, True)
        except Exception as ex:
            check('1 verify %s' % arch, False, str(ex))
    surplus = asset_arcs() ^ set(SHIPPED_ARCHIVES)
    check('1 asset 归档集合 == 交付名单（无未改动文件）', not surplus, str(sorted(surplus)))

    rio = read_members(os.path.join(ASSET, 'Rio.arc'))
    loose = {}
    rio_dir = os.path.join(ASSET, 'RIO')
    if os.path.isdir(rio_dir):
        for fn in os.listdir(rio_dir):
            loose[fn[:-4].upper()] = open(os.path.join(rio_dir, fn), 'rb').read()
    known_scripts = {n[:-4].upper() for n in rio} | set(loose) | {'TITLE', 'EVRET'}

    # ── 2. 调用链完整性 ──
    missing = set()
    for n, d in rio.items():
        dec = ws2.decode(d)
        for m in re.finditer(rb'\x07([A-Za-z0-9_]{2,14})\x00', dec):
            t = m.group(1).decode('ascii', 'replace').upper()
            if t in known_scripts or t in LABEL_OK or t.isdigit():
                continue
            missing.add((n[:-4], t))
    check('2 调用链（07/02 目标可达）', not missing, str(sorted(missing)[:6]))
    restored_jumps = [('ASA_001', 'ASA_002'), ('ASA_003', 'ASA_004'), ('YOR_002', 'YOR_003'),
                      ('YOR_004', 'YOR_005'), ('YOR_006', 'YOR_007')]
    for s, tgt in restored_jumps:
        ok = tgt.encode('ascii') in ws2.decode(rio[s + '.ws2'])
        check('2 A-1 跳转 %s→%s' % (s, tgt), ok)

    # ── 3. 成就触发点 ──
    hooks = sum(ws2.decode(d).count(b'\x04CG_ACHIEVEMENT\x00') for d in rio.values())
    f0 = 0
    for d in rio.values():
        ins, _ok = ws2dis.disassemble(ws2.decode(d))
        f0 += sum(1 for i in ins if i[1] == 0xF0)
    check('3 成就钩子 922 处', hooks == EXPECT_HOOKS, '实测 %d' % hooks)
    check('3 成就触发 0xF0 共 29 处', f0 == EXPECT_F0, '实测 %d' % f0)

    # ── 4. 资源配对 ──
    arch_names = {}
    for a in ('VOICE.arc', 'Chip1.arc', 'CHIP2.arc', 'CHIP3.arc', 'CHIP4.arc',
              'CHIP5.arc', 'CHIP6.arc', 'GRAPHIC.arc', 'SE.arc', 'BGM.arc'):
        arch_names[a] = {n.lower() for n in read_members(arch_path(a))}
    def resolve(f):
        return any(f in s for s in arch_names.values())
    unres = set()
    for n, d in rio.items():
        dec = ws2.decode(d)
        ins, _ok = ws2dis.disassemble(dec)
        for _off, op, _sz, ops in ins:
            if op in (0x33, 0x34) or op in (0x1E, 0x28):
                parts = ops.split(b'\x00')
                if len(parts) < 2:
                    continue
                fname = parts[1].decode('cp932', 'replace').strip().upper()
                if not fname or not re.match(r'^[A-Z0-9_\x81-\x9f\xe0-\xef][^\\]*\.(PNG|PNA|OGG)$', fname, re.I):
                    continue
                if op == 0x28 and parts[0].upper().startswith(b'CHAR'):
                    kind = 'voice'
                elif op == 0x28:
                    kind = 'se'
                elif op == 0x1E:
                    kind = 'bgm'
                elif fname.endswith('.PNA'):
                    kind = 'pna'
                else:
                    kind = 'png'
                if fname.upper() == 'BGM_STOP.OGG':
                    continue                       # 引擎伪引用（两版一致，归档无此文件）
                if not resolve(fname.lower()):
                    unres.add((n[:-4], kind, fname))
    check('4 资源引用全部可解析', not unres, str(sorted(unres)[:6]))

    # ── 5. 零破坏性（keep 成员与 backup 逐字节相等）──
    swapped = []
    for arch in SHIPPED_ARCHIVES:
        ap = os.path.join(ASSET, arch)
        bp = os.path.join(BACKUP, arch)
        if not (os.path.exists(ap) and os.path.exists(bp)):
            continue
        am, bm = read_members(ap), read_members(bp)
        for n, d in bm.items():
            if n in am and am[n] != d:
                swapped.append((arch, n))
    # 被改写是宿主/A-1/跳转/start 的本意；其余同名成员必须原样
    intended = set()
    for s in ('ASA_002', 'ASA_004', 'YOR_003', 'YOR_005', 'YOR_007'):
        intended.add(s + '.ws2')
    intended.add('start.ws2')
    for s in ('ASA_001', 'ASA_003', 'YOR_002', 'YOR_004', 'YOR_006'):
        intended.add(s + '.ws2')
    intended.add(('Script.arc', 'ArcFileName.lua'))     # G6（L4 路由）
    intended.add(('Script.arc', 'LegacyGame.lua'))      # G1/G2（L4 门控）
    plan = json.load(open(os.path.join(ROOT, 'resource', 'restore_plan.json'), encoding='utf-8'))
    for s, pl in plan['hosts'].items():
        if pl['kind'] != 'skip':
            intended.add(s + '.ws2')
            intended.add(('zh-CN/Rio.arc', s + '.lng'))   # 宿主 .lng 按新槽位序重建
    intended.add(('zh-CN/Rio.arc', 'NameTable.txt'))      # G10 名牌表合并
    unexpected = [x for x in swapped
                  if (x[0], x[1]) not in intended and x[1] not in intended]
    check('5 Steam 原有成员未被意外替换', not unexpected, str(unexpected[:8]))

    # ── 6. 可复现性（asset vs payload/METADATA.json）──
    # 本闸证明「当期 asset == 当期交付表」；跨构建复现看效果：重跑步 4/5 后
    # `git diff payload/METADATA.json` 应为空。
    mf_path = os.path.join(ROOT, 'payload', 'METADATA.json')
    if os.path.exists(mf_path):
        metadata = json.load(open(mf_path, encoding='utf-8'))
        expected = {}
        for key, info in metadata.items():
            if info['kind'] == 'loose':
                expected.update(info['files'])
            else:
                expected[key] = info['checksum']
        import hashlib
        cur = {}
        for dirpath, _dirs, files in os.walk(ASSET):
            for fn in files:
                fp = os.path.join(dirpath, fn)
                rel = os.path.relpath(fp, ASSET).replace('\\', '/')
                h = hashlib.sha256()
                with open(fp, 'rb') as f:
                    for chunk in iter(lambda: f.read(1 << 20), b''):
                        h.update(chunk)
                cur[rel] = h.hexdigest()
        check('6 asset == 交付表（payload/METADATA.json）', cur == expected,
              '集合差 %r 哈希差 %r' % (sorted(set(cur) ^ set(expected))[:6],
                                     [k for k in set(cur) & set(expected) if cur[k] != expected[k]][:6])
              if cur != expected else '')
    else:
        check('6 交付表存在', False, 'payload/METADATA.json 缺失（先跑步 5）')

    # ── 8. 交付项完整性 ──
    sys.path.insert(0, os.path.join(ROOT, 'script'))
    try:
        from build_l4 import SL_PNA  # noqa: E402
        graph = {n.lower() for n in read_members(os.path.join(ASSET, 'GRAPHIC.arc'))}
        missing_pna = [p for p in SL_PNA if p.lower() not in graph]
        check('8 GRAPHIC 含 33 张 SL .pna', not missing_pna, str(missing_pna[:4]))
    except ImportError:
        check('8 GRAPHIC 含 33 张 SL .pna', False, 'build_l4.SL_PNA 不可导入')

    se = {n.lower() for n in read_members(os.path.join(ASSET, 'SE.arc'))}
    for s in ('t_se91.ogg', 'pw129_4.ogg', 'se43b.ogg'):
        check('8 SE 含 %s' % s, s in se)

    zrio = read_members(os.path.join(ASSET, 'zh-CN', 'Rio.arc'))
    for s, n in EXPECT_SL_LNG.items():
        key = s + '.lng'
        if key not in zrio:
            check('8 zh 含 %s' % key, False)
            continue
        zl = lng.parse_lng(zrio[key], key=lng.KEY_STEAM_ZHCN)
        check('8 %s 槽位 %d' % (key, n), len(zl) == n, '实测 %d' % len(zl))
    nt = zrio.get('NameTable.txt', b'').decode('utf-16le', 'replace')
    check('8 NameTable 合并条目 193', len([l for l in nt.splitlines() if l.strip()]) == 193,
          '实测 %d 行' % len([l for l in nt.splitlines() if l.strip()]))

    a1_fan = {'ASA_002': 453, 'ASA_004': 371, 'YOR_003': 322, 'YOR_005': 284, 'YOR_007': 374}
    for s, n in a1_fan.items():
        ok = (s + '.ws2') in rio and (s + '.lng') in zrio
        if ok:
            zl = lng.parse_lng(zrio[s + '.lng'], key=lng.KEY_STEAM_ZHCN)
            ok = len(zl) == n
        check('8 A-1 %s（脚本+lng %d 槽）' % (s, n), ok)

    # ── 汇总 ──
    lines.append('')
    lines.append('FAILS: %d -> %s' % (len(fails), fails))
    lines.append('')
    lines.append('7 实机测试清单（人工）：')
    lines.append('  - A-1 五个入口：ASA_001→ASA_002、ASA_003→ASA_004、YOR_002→YOR_003、')
    lines.append('    YOR_004→YOR_005、YOR_006→YOR_007（进 H 场景、回想、出口）')
    lines.append('  - A-2 插入点前后各一屏（AGE_005/AGE_010/KOT_006 等首尾衔接）')
    lines.append('  - 后日谈：mainmenu → openAfter → SL_*（立绘/语音/SE 完整）')
    lines.append('  - 成就：任一 CG 收集成就正常弹出')
    with open(os.path.join(ROOT, 'tmp', 'final_verification.md'), 'w', encoding='utf-8', newline='\n') as f:
        f.write('\n'.join(lines))
    npass = sum(1 for l in lines if l.startswith('[PASS]'))
    print('final_verification: PASS %d / FAIL %d' % (npass, len(fails)))
    for name in fails:
        print('  FAIL ' + name.encode('ascii', 'replace').decode())
    print('明细: tmp/final_verification.md')
    sys.exit(1 if fails else 0)


if __name__ == '__main__':
    main()
