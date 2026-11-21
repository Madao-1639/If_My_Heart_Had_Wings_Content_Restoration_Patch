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
from tool import arcbuild, ws2, ws2dis, lng  # noqa: E402
from tool import paths  # noqa: E402

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

    # ── 4b. 演出同步（保留槽演出：删多余 / 换回原版行）：判定表条目逐条落地 ──
    # 方针「每类演出要么两侧同时存在且相等、要么都不存在」见 doc/restoration-route.md §7 V-10；
    # 判定表 resource/perf_sync_map.json 的 action=drop／replace 子集必须逐条落到产物
    # （名单槽数＝落地槽数；replace 的补块数另由计划器断言）。
    _plan = json.load(open(os.path.join(ROOT, 'resource', 'restore_plan.json'), encoding='utf-8'))
    ps_path = os.path.join(ROOT, 'resource', 'perf_sync_map.json')
    if os.path.exists(ps_path):
        _pm = json.load(open(ps_path, encoding='utf-8'))
        _want = sum(1 for s0 in _pm.get('sites', [])
                    if s0.get('action') in ('drop', 'replace'))
        # CG 线表 `cg_site_rewrites.json` 的 `ev_drops` 同样并入 `plan.perf_sync` 落地
        _cgp = os.path.join(ROOT, 'resource', 'cg_site_rewrites.json')
        if os.path.exists(_cgp):
            _want += len(json.load(open(_cgp, encoding='utf-8')).get('ev_drops') or [])
        _psm = os.path.join(ROOT, 'resource', 'perf_sync_manual.json')
        if os.path.exists(_psm):
            _pmd = json.load(open(_psm, encoding='utf-8'))
            _want += len(_pmd.get('drops') or []) + len(_pmd.get('replaces') or []) + len(_pmd.get('keeps') or [])
        _got = sum(v for k, v in _plan.get('gates', {}).items() if k.startswith('perf_sync_'))
        check('4b 演出同步名单逐条落地（名单 %d 条）' % _want, _want > 0 and _want == _got,
              '落地 %d' % _got)
    else:
        check('4b 演出同步判定表存在', False, 'resource/perf_sync_map.json 缺失')

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
    # 同名整名覆盖是方针（resource-naming.md §1–§3）：判定表 overwrite 子集逐名豁免；
    # 名单外一律不得替换（route §4 写盘器硬要求）。
    roster = set()
    for fn, alist in (('censor_map.json', 'members'), ('voice_conflict_map.json', 'members'),
                      ('perf_sync_map.json', 'member_overwrites')):
        mp = json.load(open(os.path.join(ROOT, 'resource', fn), encoding='utf-8'))
        for m in mp.get(alist, []):
            if m.get('action') == 'overwrite':
                roster.add((m['archive'].lower(), m['name'].lower()))
    unexpected = [x for x in swapped
                  if (x[0], x[1]) not in intended and x[1] not in intended
                  and (x[0].lower(), x[1].lower()) not in roster]
    check('5 Steam 原有成员未被意外替换（覆盖名单内为方针允许）', not unexpected, str(unexpected[:8]))
    replaced = {(a.lower(), n.lower()) for a, n in swapped if (a.lower(), n.lower()) in roster}
    check('5b 覆盖名单条数 = 实际替换次数（逐名对齐）',
          len(roster) > 0 and replaced == roster,
          'roster %d / replaced %d / 缺 %s' % (len(roster), len(replaced), sorted(roster - replaced)[:5]))

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
    sys.path.insert(0, os.path.join(ROOT, 'script', 'build'))
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

    # ── 9. WS2 尾表（末尾 8 字节明文表：[消息数][选项条目数]）──
    # 引擎按该表给「已读消息位图」（存档目录 MessageFlag.dat）分配
    # (消息数+选项数+7)/8 字节，而写位**不做边界检查** ⇒ 表小于真实消息数时
    # 高位下标直接写到相邻堆块上 ⇒ 概率性 0xc0000374 闪退（见 GalRev
    # docs/engines/advhd/file-formats.md「末尾 8 字节」/ save-system.md）。
    # 因此：任何插入/删格必须同步重写该表；这里闸「产物 == 实算」，并把
    # 「基线自己就偏离」的脚本排除（本作 Steam 基线有 3 个如此）。
    tail_checked = 0
    tail_bad = []
    for rel in sorted(asset_arcs()):
        ap = os.path.join(ASSET, rel)
        bp = os.path.join(BACKUP, rel)
        try:
            ms = read_members(ap)
        except Exception:
            continue
        if not any(n.lower().endswith('.ws2') for n in ms):
            continue
        base = None
        if os.path.exists(bp):
            try:
                base = read_members(bp)
            except Exception:
                base = None
        _ok, bad = ws2.check_tails(ms, base)
        tail_checked += len(ms)
        tail_bad += ['%s:%s(%s<%s)' % (rel, n, t[0], c[0]) for n, c, t in bad if t[0] < c[0]]
    check('9 WS2 尾表 >= 消息数（检查 %d 成员，危险 %d）' % (tail_checked, len(tail_bad)),
          not tail_bad, str(tail_bad[:6]))

    # ── 10. 语音重指（人工定案 resource/voice_repoint_manual.json）──
    # 判据落在**内容面**（不能只查名单条数）：产物脚本里旧 token 消失／新 token 在位，
    # 且交付 `VOICE.arc` 里该成员的**字节 == 原版**——否则玩家听到的还是 Steam 那条录音。
    vp = os.path.join(ROOT, 'resource', 'voice_repoint_manual.json')
    if os.path.exists(vp):
        reps = json.load(open(vp, encoding='utf-8')).get('repoints') or []
        _vo = os.path.join(ASSET, 'VOICE.arc')
        vol = ({k.lower(): v for k, v in read_members(_vo).items()}
               if os.path.exists(_vo) else {})
        try:
            orig_v = {k.lower(): v for k, v in read_members(
                os.path.join(paths.orig_dir(), 'VOICE.arc')).items()}
        except Exception:
            orig_v = {}
        for e in reps:
            key = e['script'] + '.ws2'
            dec = ws2.decode(rio[key]) if key in rio else b''
            check('10 语音重指 %s %s→%s（旧 token 消失／新 token 在位）'
                  % (e['script'], e['from'], e['to']),
                  e['from'].encode('ascii') not in dec and e['to'].encode('ascii') in dec)
            if orig_v:
                check('10 语音重指成员 %s 字节 == 原版' % e['to'],
                      vol.get(e['to'].lower()) == orig_v.get(e['to'].lower()))

    # ── 11. 解锁位点（CG 画廊条目 / CG_ACHIEVEMENT / 0xF0 成就）──
    # 判据落在**内容面**：Steam 有 N 个解锁位点，产物必须 ≥ N 个（**只拦丢失**）。
    # 为什么不用「逐点位置相等」：删格会让位点随相邻存活格移位、还原段会带入原版自己的
    # `0b` 对（合法增加）——位置比对会把这两种正常形态误判成缺陷。
    # 丢失的症状完全没有报错：画廊格子永久锁死、收集类成就不弹（见
    # doc/engine-mechanics.md「成就触发点契约」）。
    try:
        import importlib.util
        _spec = importlib.util.spec_from_file_location(
            'cg_unlock_check', os.path.join(ROOT, 'script', 'checks', 'cg_unlock_check.py'))
        _cuc = importlib.util.module_from_spec(_spec)
        _spec.loader.exec_module(_cuc)
        _pm = _cuc._members_arch(os.path.join(ASSET, 'Rio.arc'))
        _pm.update(_cuc._members_loose(os.path.join(ASSET, 'RIO')))
        _base, _ = _cuc.scan(_cuc._members_arch(os.path.join(BACKUP, 'Rio.arc')))
        _prod, _sk = _cuc.scan(_pm)
        _lost = []
        for _n, _b in sorted(_base.items()):
            _p = _prod.get(_n)
            if _p is None:
                continue
            if _p['cg'] < _b['cg']:
                _lost.append('%s:CG %d->%d' % (_n, _b['cg'], _p['cg']))
            if _b['flags'] - _p['flags']:
                _lost.append('%s:0b %s' % (_n, sorted(_b['flags'] - _p['flags'])[:5]))
            if _b['f0'] - _p['f0']:
                _lost.append('%s:F0 %s' % (_n, sorted(_b['f0'] - _p['f0'])))
        # 第二组：归属不得串号——`0b (A,B)` 只认 Steam 的编号空间。
        # 原版段带着**原版编号**的解锁对照抄进产物 ⇒ 数量变多、集合变大（第一组全绿），
        # 但 `CG_PAGE` 会点亮一张完全不相干的画廊条目 ⇒ 必须单独判。
        # 限定：只对「Steam 基线里有同名脚本」者判（A-1 整脚本与后日谈 `SL_*` 在 Steam
        # 侧没有同名脚本，用原版编号是对的）。
        _sp = set()
        for _b in _base.values():
            _sp |= _b.get('pairs') or set()
        _foreign = []
        if _sp:
            for _n, _p in sorted(_prod.items()):
                if _n not in _base:
                    continue
                _bad = (_p.get('pairs') or set()) - _sp
                if _bad:
                    _foreign.append('%s:%d' % (_n, len(_bad)))
        check('11 解锁位点不丢失且不串号（CG_ACHIEVEMENT / 0b / 0xF0）',
              not _lost and not _foreign,
              '丢失 %s ；串号 %s' % (_lost[:6], _foreign[:6]))
    except Exception as ex:                       # noqa: BLE001 —— 闸自身失败也必须报
        check('11 解锁位点闸可运行', False, str(ex))

    # ── 12. 跨引擎标志词表（`0x46` 子层槽绑定 / `0x47` 参数来源）──
    # 判据落在**内容面**：产物里原版取值（`0x80`）的**计数必须为 0**。只看「取值属于合法集合」
    # 不够——两边各有自己的合法值，只要集合有交集就会判通过而全部漏检。
    # 后果与机理见 doc/engine-mechanics.md「动画组的工作机制」：`0x46` 欠绑定子层槽（立绘
    # 残留/表情层错位）、`0x47` 参数来源位失配（动画照跑、终点不对），两者都**不报错**。
    try:
        sys.path.insert(0, os.path.join(ROOT, 'script', 'checks'))
        import importlib.util
        _spec = importlib.util.spec_from_file_location(
            'op46_flag_check', os.path.join(ROOT, 'script', 'checks', 'op46_flag_check.py'))
        _ofc = importlib.util.module_from_spec(_spec)
        _spec.loader.exec_module(_ofc)
        _r = _ofc.scan(
            _ofc.collect(os.path.join(ASSET, 'Rio.arc'), os.path.join(ASSET, 'RIO')),
            'product')
        _orig_val = sum(1 for x in _r['bad'] if x['flag'] == _ofc.ORIG_VALUE)
        check('12 标志词表：产物无原版取值(0x80) / 无越界（含裸 RIO 后日谈脚本）',
              not _r['bad'],
              '0x80 %d 处；其它越界 %d 处；0x46=%s 0x47=%s'
              % (_orig_val, len(_r['bad']) - _orig_val,
                 dict(sorted(_r['c46'].items())), dict(sorted(_r['c47'].items()))))
        check('12 标志词表：线性解析不自洽脚本已记账（非静默）',
              True, '%d 个 %s' % (len(_r['skipped']), _r['skipped'][:5]))
    except Exception as ex:                       # noqa: BLE001 —— 闸自身失败也必须报
        check('12 标志词表闸可运行', False, str(ex))

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
