# -*- coding: utf-8 -*-
"""演出同步判定表生成器（产出端脚本，管线步 2d）。

方针（见 doc/restoration-route.md §6 V-10）
----------------------------
**与原版相比，每类演出（语音 / CG / 立绘 / 背景）要么两侧同时存在且相等，要么都不存在。**

本表把这条方针落成逐槽判定：对齐的 (Steam 保留槽 ↔ 原版行) 对里，**Steam 保留槽自带**
（own，即该槽演出前缀区内、上一条 `0x14` 之后）的显示演出，若原版对齐行**在屏**没有
这张图，就是「多余的 Steam 演出」⇒ `action=drop`，由写盘器删掉那一块。

为什么只有本表能拦住（见 doc/restoration-route.md §6 V-10）
--------------------------------------------------------
Steam 把原版**事件 CG 的显示点换成背景 + 立绘**（两侧**异名**）：
  · 同名冲突判定表 `censor_map.json` 入口是「同名两侧字节不同」⇒ 不进表；
  · 语音机检只看语音、文本机检只看台词（两侧同句就算过）⇒ 全看不见；
  · `cg_site_rewrites.json` 只覆盖「CG 显示点本身」（随行带入 `0x33`），
    **不覆盖它周围保留槽的演出前缀**——于是产物里 CG 与 Steam 立绘/背景同屏。
本表按「逐槽演出状态对账」补上这条通道。判据与命名差异见 `tool/perfsync.py`。

对齐与可信度
------------
* 对齐：Steam 槽 → 原版行取自 `resource/carrier_map.json` 的 `anchor`／`match`
  **等长 1:1** 块线性内插；只作用于**保留槽**（未被 `restore_plan` drop 的槽）。
* 可信：该对两侧**本槽自带语音号**必须相等（含两侧皆无）。不等 ⇒ 承载图 1:1 是
  **假配对**（token 骨架相等、内容不同；判据见 doc/resource-naming.md §2「对齐证据要先核实」），
  一律只登记 `review`、**不自动处置**。

用法
----
    python script/build/build_perf_sync_map.py [--orig-dir DIR] [--emit-map PATH]
                                               [--report tmp/perf_sync_map.md]

缺 `--orig-dir` 时读环境变量 `IFMH_ORIG_DIR`。
"""
import argparse
import collections
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from tool import arcbuild, ws2, ws2dis, ws2conv, perfsync, subimg  # noqa: E402
from tool import paths  # noqa: E402

OUT_MAP = os.path.join(ROOT, 'resource', 'perf_sync_map.json')
OUT_MD = os.path.join(ROOT, 'tmp', 'perf_sync_map.md')


def parse_steam(raw):
    instrs, ok = ws2dis.disassemble(ws2.decode(raw))
    assert ok, 'steam table parse not self-consistent'
    return instrs


def parse_orig(raw, ofmt):
    parsed, _tail = ws2conv.parse(ws2.decode(raw), ofmt)
    out, p = [], 0
    for op, ops in parsed:
        out.append((p, op, 1 + len(ops), ops))
        p += 1 + len(ops)
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description='演出同步判定表生成器')
    ap.add_argument('--orig-dir', default=os.environ.get('IFMH_ORIG_DIR', ''))
    ap.add_argument('--emit-map', default=OUT_MAP)
    ap.add_argument('--report', default=OUT_MD)
    a = ap.parse_args(argv)
    if not a.orig_dir or not os.path.isdir(a.orig_dir):
        sys.exit('需要原版目录：--orig-dir 或环境变量 IFMH_ORIG_DIR')

    ofmt = ws2conv.load_orig_formats(a.orig_dir)
    plan = json.load(open(os.path.join(ROOT, 'resource', 'restore_plan.json'), encoding='utf-8'))
    carrier = json.load(open(os.path.join(ROOT, 'resource', 'carrier_map.json'), encoding='utf-8'))

    def members(p):
        return {nb.decode('utf-16le', 'replace'): d for nb, d in arcbuild.read_raw(p)}

    steam_rio = members(os.path.join(paths.STEAM, 'Rio.arc'))
    orig_rio = members(os.path.join(a.orig_dir, 'Rio.arc'))
    # 子图层判据的 PNA 表：「当前加载的那个」＝Steam 归档里有该名就用 Steam 的，否则用原版的
    # （产物也是这个规则：Steam 缺的成员由 resources.copy 从原版补入）。
    cur_pna = subimg.index_pna(paths.STEAM)
    org_pna = subimg.index_pna(a.orig_dir)
    _subcache = {}

    def subtable(blob):
        k = id(blob)
        if k not in _subcache:
            _subcache[k] = subimg.subimage_table(blob)
        return _subcache[k]

    sites, review = [], []
    member_overwrites = {}          # 同名成员内容差（子图级判定）⇒ 整名覆盖为原版字节
    stat = collections.Counter()

    def arch_of_pna(name):
        """同名立绘成员在哪个归档里（Steam 侧优先，其次原版）。"""
        low = (name or '').lower()
        for root in (paths.STEAM, a.orig_dir):
            for arch in subimg.ARCHIVES:
                p = os.path.join(root, arch)
                if not os.path.exists(p):
                    continue
                for nb, _d in arcbuild.read_raw(p):
                    if nb.decode('utf-16le', 'replace').lower() == low:
                        return arch
        return None

    for script, host in sorted(plan['hosts'].items()):
        if host.get('kind') != 'host':
            continue
        key = script + '.ws2'
        if key not in steam_rio or key not in orig_rio:
            continue
        # 范围闸：只对本脚本**内容层被还原动过**（插入 / CG 显示点 / 删格）的宿主做演出同步。
        # 纯文本覆盖（如 CO1_003／CO2_002）与零改动宿主不在此列——那些脚本产物≡Steam，
        # 两侧演出差是 Steam 与原版的版本差，**不在还原范围内**（改动面收敛）。
        pl0 = host['plan']
        in_scope = bool(pl0.get('inserts') or pl0.get('cg_sites') or pl0.get('drops'))
        if not in_scope:
            stat['out_of_scope'] += 1
        s_instrs, o_instrs = parse_steam(steam_rio[key]), parse_orig(orig_rio[key], ofmt)
        s_rows, o_rows = perfsync.perf_rows(s_instrs), perfsync.perf_rows(o_instrs)
        s_ins, o_ins = perfsync.row_instrs(s_instrs), perfsync.row_instrs(o_instrs)
        # 对齐：承载图 anchor/match 等长块内插 ＋ **语音号自证**补 `ambiguous` 块里的缺口
        s2o = perfsync.interp_align(perfsync.voice_align(
            [r['own'] for r in s_rows], [r['own'] for r in o_rows],
            perfsync.align_map(script, carrier), override=True))
        drops = set(host['plan']['drops'])
        # **范围＝脚本级，不做行级收窄**：不可用「还原内容在屏」把范围收到
        # 还原段内，但那会把**分歧的根**切掉——状态是延续量，分歧一旦在某槽产生就会一直带到
        # 还原段里（实测 `AGE_010` s23→o23 的对齐定案因 `in_scope=False` 无处施力）。脚本级
        # 范围（只动「内容层被还原动过」的宿主）已足够约束改动面，槽级另由「对齐可信」把关。
        # 原版**全脚本**出现过的图名集合：产物自带而此集合外者＝Steam 新增素材，
        # **与对齐无关**（不需要 1:1 对齐即可判定），是本表第二类 `extra`。
        orig_imgs = set()
        for rw in o_rows:
            orig_imgs |= perfsync.images(rw['eff'])
        site_of = {}

        def add_site(k, chans, kind, prod, orig, voice, mode='drop', orig_row=None,
                     _so=site_of, _sc=script):
            e = _so.get(k)
            if e is None:
                e = {'script': _sc, 'slot': k,
                     'orig_row': orig_row if orig_row is not None else s2o.get(k),
                     'action': mode, 'kind': kind, 'channels': sorted(set(chans)),
                     'prod': dict(prod), 'orig': dict(orig), 'voice': voice,
                     'evidence': 'doc/restoration-route.md §6 V-10'}
                _so[k] = e
                sites.append(e)
            else:
                if mode == 'replace':                    # replace 覆盖 drop（它连删带补）
                    e['action'] = 'replace'
                    e['orig_row'] = orig_row
                    e['kind'] = kind
                e['channels'] = sorted(set(e['channels']) | set(chans))
                e['prod'].update(prod)
                e['orig'].update(orig)

        # 第二类（对齐无关）：产物自带、原版全脚本都不出现的图 ⇒ 一定是多余演出。
        # 仅限**内容层被还原动过**的宿主（其余宿主的演出差是版本差，不在还原范围）。
        if in_scope:
            for k in range(len(s_rows)):
                if k in drops:
                    continue
                own = s_rows[k]['own'].get('display') or {}
                absent = {c: n for c, n in own.items()
                          if perfsync.sb_chan(c, n) and n not in orig_imgs}
                if absent:
                    add_site(k, absent.keys(), 'extra_absent', absent, {},
                             (s_rows[k]['own'].get('voice') or [None])[0])
                    stat['absent_slots'] += 1
                    stat['absent_chans'] += len(absent)

        for k in sorted(s2o):
            if k in drops:                       # 被删槽的演出随删格清掉，不再同步
                continue
            r = s2o[k]
            if k >= len(s_rows) or r >= len(o_rows):
                stat['pair_oob'] += 1
                continue
            P, O = s_rows[k], o_rows[r]
            stat['pairs'] += 1
            # 可信：两侧本槽自带语音号**相等**（含两侧皆无）。不等即判承载图假配对 ⇒ 不自动处置
            # ——实测放宽为「原版无语音也采信承载图」会放进 4 个**假锚**（EN 与日文明显不是同一句，
            # 如 AGE_005 s182「You really think so?」↔「あげはの指が、胸元に動く。」），
            # 会把别的行的演出搬过来。宁可留 REVIEW 交人工，也不静默搬错（见 doc/restoration-route.md §6 V-10）。
            pv, ov = P['own'].get('voice'), O['own'].get('voice')
            # 人工定案（`resource/align_fixes.json`）按「同句」核过 ⇒ 直接可信；否则只认
            # 「两侧自带语音号相等」。
            trust = (pv == ov) or ((script, k) in perfsync.align_fixes())
            if not trust:
                stat['untrusted'] += 1
            extra, rev, ev_extra = perfsync.classify(P['own'], P['eff'], O['eff'])
            # `missing` 一律不在此登记：产出端只看得到 Steam 流，看不到还原后的产物，
            # 「原版有、产物没有」必须由闸（script/checks/perf_sync_check.py）在产物上判。
            rev = [x for x in rev if x['kind'] != 'missing']
            if in_scope and extra and trust:
                add_site(k, extra, 'extra', {c: P['own']['display'].get(c) for c in extra},
                         {c: O['eff'].get(c) for c in extra},
                         (P['own'].get('voice') or [None])[0])
                stat['extra_slots'] += 1
                stat['extra_chans'] += len(extra)
            # ── 第二方向：**把该槽自带的立绘/背景演出整段换成原版行的** ──
            # 触发＝两侧「本槽自带的立绘/背景图名集合」不等（含一侧有清屏）；`ev` 不在
            # 此列（CG 序列另有 cg_site_rewrites + cg_seq_check 专管）。资源名照抄原版，
            # 由 resources.copy 把原版素材补入产物归档（补素材、不重写本版名）。
            p_sb = {c: n for c, n in (P['own'].get('display') or {}).items()
                    if perfsync.sb_chan(c, n)}
            o_sb = {c: n for c, n in (O['own'].get('display') or {}).items()
                    if perfsync.sb_chan(c, n)}
            p_clr = {c for c in (P['own'].get('clear') or ()) if c.startswith(('st', 'bg'))}
            o_clr = {c for c in (O['own'].get('clear') or ()) if c.startswith(('st', 'bg'))}
            # 判据按**通道→图名**比（不是图名集合）——两版把同一张图放在不同通道号时，
            # 只比图名集合会漏掉「通道号错位」，而错位会在后续清屏/换图时发散（见 §27）。
            if in_scope and trust and (p_sb != o_sb or p_clr != o_clr):
                add_site(k, sorted(set(p_sb) | set(o_sb)), 'replace', p_sb, o_sb,
                         (P['own'].get('voice') or [None])[0], mode='replace', orig_row=r)
                stat['replace_slots'] += 1
            # ── 第三方向：**同一姿势、不同子图编排**（Steam 改画/重排了立绘的差分层）──
            # 脚本用 `0x39`（建层）列出**子图层 id**，引擎就按这些 id 取图 ⇒ 只比归一后的
            # 图名会静默放过（实测两种：id 列表不同；id 列表相同但同 id 上的图不同）。
            # 判据＝逐位比「当前加载的 PNA 在该 id 的子图」与「原版对应子图」（字节级或像素级
            # 任一相同即算同）；只要有一位不同 ⇒ 该槽整段换成原版行（带回原版图名 + 原版 id 列表）。
            # **范围：全部宿主**（不分是否被还原动过）——立绘差分被改画是**内容面**改动
            # （Steam 把部分差分变体换成了重复图），不是版本差（实机症状：立绘表情与场景不符）。
            if trust and not (site_of.get(k) and site_of[k]['action'] == 'replace'):
                pb = [b for b in perfsync.image_blocks(s_ins[k])
                      if b['kind'] == 'display' and (b['chan'] or '').startswith('st')]
                ob = [b for b in perfsync.image_blocks(o_ins[r])
                      if b['kind'] == 'display' and (b['chan'] or '').startswith('st')]
                if pb and ob and (pb[0]['name'] or '').lower().endswith('.pna'):
                    ids_cur = perfsync.layer_ids(s_ins[k], pb[0]['chan'])
                    ids_org = perfsync.layer_ids(o_ins[r], ob[0]['chan'])
                    if ids_cur and ids_org:
                        org_name = perfsync.norm_sprite((ob[0]['name'] or '').upper())
                        v = perfsync.subimage_verdict(
                            subtable(subimg.resolve(cur_pna, org_pna, pb[0]['name'])),
                            subtable(org_pna.get(org_name.lower())), ids_cur, ids_org)
                        if v != 'same':
                            pc = {b['chan']: b['name'] for b in pb if b['name']}
                            oc = {b['chan']: b['name'] for b in ob if b['name']}
                            add_site(k, sorted(set(pc) | set(oc)), 'layer', pc, oc,
                                     (P['own'].get('voice') or [None])[0],
                                     mode='replace', orig_row=r)
                            site_of[k]['evidence'] = (
                                'doc/resource-naming.md §3（立绘差分层编排：脚本列的子图层 id 上的子图与原版不同；'
                                '图名归一后相同 ⇒ 只看图名会漏）')
                            stat['layer_slots'] += 1
                            # 「同名成员内容差」：两侧**同名**（Steam 基线里也有这个名）而该成员
                            # 在**原版块列的 id** 上的子图与原版不同 ⇒ 整名覆盖为原版字节
                            # （脚本与调用点都不动）。这一步与「异名」无关，**两种情形的产物都会
                            # 落到它**：异名槽被 replace 成原版行后，图名也变成这个同名成员。
                            for _chan, _oname in oc.items():
                                _low = (_oname or '').lower()
                                if (not _low.endswith('.pna') or _low not in cur_pna
                                        or _low not in org_pna):
                                    continue
                                _ids = perfsync.layer_ids(o_ins[r], _chan)
                                if not _ids:
                                    continue
                                if perfsync.subimage_verdict(subtable(cur_pna[_low]),
                                                             subtable(org_pna[_low]),
                                                             _ids, _ids) != 'same':
                                    member_overwrites[_low] = {
                                        'archive': arch_of_pna(_oname), 'name': _oname,
                                        'orig_name': _oname,
                                        'reason': '%s 的立绘成员两侧**同名**但子图不同（原版行 o%d '
                                                  '在 id %s 上用的是原版那张）⇒ 整名覆盖为原版字节，'
                                                  '脚本与调用点不动。' % (script, r, _ids)}
                                    stat['member_overwrites'] += 1
            # review 只记**还没处置**的差异：已被本槽 site 覆盖的通道不再重复登记
            # （否则评审要花力气分辨「重复登记」与「真漏处置」）。
            _done = set((site_of.get(k) or {}).get('channels') or ())
            rev2 = [x for x in rev if x['chan'] not in _done]
            extra2 = [c for c in extra if c not in _done]
            if rev2 or ev_extra or (extra2 and not trust):
                review.append({'script': script, 'slot': k, 'orig_row': r, 'trusted': trust,
                               'extra': extra2, 'ev_extra': ev_extra, 'items': rev2,
                               'prod_voice': P['own'].get('voice'),
                               'orig_voice': O['own'].get('voice')})
                stat['review_slots'] += 1

        # 插入的**原版行**：其图像演出块就是原版的 ⇒ 直接按它自己的图名与 id 做同名成员检查
        # （不依赖对齐、也不受「可信闸」限制：这里比的就是原版行本身）。
        srcs = (pl0.get('slot_sources') or [])
        for k, src in enumerate(srcs):
            if k >= len(s_ins) or not src or src[0] != 'orig':
                continue
            for b in perfsync.image_blocks(s_ins[k]):
                if b['kind'] != 'display' or not (b['chan'] or '').startswith('st'):
                    continue
                low = (b['name'] or '').lower()
                if not low.endswith('.pna') or low not in cur_pna or low not in org_pna:
                    continue
                ids = perfsync.layer_ids(s_ins[k], b['chan'])
                if not ids:
                    continue
                if perfsync.subimage_verdict(subtable(cur_pna[low]), subtable(org_pna[low]),
                                             ids, ids) != 'same':
                    member_overwrites[low] = {
                        'archive': arch_of_pna(b['name']), 'name': b['name'],
                        'orig_name': b['name'],
                        'reason': '%s 插入的原版行 p%d 引用同名立绘 %s，但 id %s 上的子图在'
                                  'Steam 侧成员里与原版不同 ⇒ 整名覆盖为原版字节，脚本不动。'
                                  % (script, k, b['name'], ids)}
                    stat['member_overwrites'] += 1

    doc = {
        'meta': {
            'purpose': '演出同步判定表：对齐的 (Steam 保留槽 ↔ 原版行) 对里，Steam 保留槽自带、'
                       '原版对齐行在屏没有的立绘/背景显示 ⇒ 写盘器删除该槽演出前缀区内这一显示块。',
            'producer': 'script/build/build_perf_sync_map.py',
            'consumer': 'script/build/build_restore_plan.py',
            'policy': '与原版相比，每类演出（语音 / CG / 立绘 / 背景）要么两侧同时存在且相等，'
                      '要么都不存在。',
            'alignment': 'Steam 槽 → 原版行：resource/carrier_map.json 的 anchor/match 等长 1:1 '
                         '块线性内插；只作用于保留槽（未被 restore_plan drop 的槽）。',
            'trust': '该对两侧本槽自带语音号必须相等（含两侧皆无）；不等即判承载图 1:1 假配对，'
                     '只登记 review、不自动处置。',
            'judgement': '判据实现见 tool/perfsync.py：按「在屏图名集合」判多不多，容忍两版'
                         '背景通道号错位（原版 bg01 ↔ Steam bg02）；立绘先按两套命名归一。',
            'sprite_normalization': perfsync.SPRITE_MAP,
            'kinds': {
                'extra': 'Steam 保留槽自带、原版对齐行在屏没有（该图名原版本脚本有）⇒ 删该通道',
                'extra_absent': 'Steam 保留槽自带、原版**全脚本**都不出现的图名（Steam 新增素材）'
                                '⇒ 删该通道（**与对齐无关**，不需 1:1 对齐即可判定）',
                'replace': '该槽自带的立绘／背景演出与原版对齐行的**不等** ⇒ 整段换成原版行的'
                           '（删该槽全部立绘／背景显示块与清屏指令，再补原版行的图像演出块；'
                           '资源名照抄原版，靠 resources.copy 补入原版素材）',
                'missing': '原版在屏有、产物没有 ⇒ review（对齐不可信时不自动补）',
                'layer': '该槽的立绘**图名归一后与原版相同**，但脚本列的**子图层 id 上的子图不同**'
                         '（Steam 改画/重排了差分层）⇒ 整段换成原版行（同 replace 动作）。',
                'different': '两侧同通道取值不同（且原版那张图产物没有）⇒ review',
                'ev_extra': 'ev 通道的差异 ⇒ review（CG 序列另有 cg_seq_check.py + cg_site_rewrites 专管）',
            },
            'actions': {
                'drop': '删该槽演出前缀区内、这些通道的显示块（显示指令与其图层伴生：39／'
                        '04 LAYER_ORDER／09／46／3e／65，前置 64）；0b 状态写入与流程控制保留。',
                'replace': '先按 drop 删该槽**全部立绘／背景**显示块与清屏指令，再把原版对齐行的'
                           '图像演出块（按原顺序、照抄原版资源名）在**该槽前缀区开头**补回'
                           '（排在语音／名字框之前）。',
            },
            'note': '本表按「逐槽演出状态对账」补 censor_map（同名）与 cg_site_rewrites（CG 显示点）'
                    '两条通道都管不到的『异名演出改动』。',
        },
        'sites': sites,
        'review': review,
        'summary': dict(stat),
        'member_overwrites': sorted(member_overwrites.values(), key=lambda e: e['name'].lower()),
    }
    with open(a.emit_map, 'w', encoding='utf-8', newline='\n') as f:
        json.dump(doc, f, ensure_ascii=False, indent=1)
        f.write('\n')

    md = ['# 演出同步判定表（产出端）', '',
          '- 对齐对 %d；不可信 %d' % (stat['pairs'], stat['untrusted']),
          '- 处置：replace %d 槽 ／ drop（extra %d + extra_absent %d）槽' % (
              stat['replace_slots'], stat['extra_slots'], stat['absent_slots']),
          '- review（不自动处置）：%d 槽' % stat['review_slots'], '',
          '## 处置（写盘器动作）', '']
    for s in sites:
        md.append('- `%s` slot %s ↔ orig %s **%s** ｜ chans=%s ｜ prod=%s ｜ orig=%s ｜ voice=%s'
                  % (s['script'], s['slot'],
                     '—' if s['orig_row'] is None else s['orig_row'],
                     s['action'], s['channels'], s['prod'], s['orig'], s['voice']))
    md += ['', '## review', '']
    for r in review:
        md.append('- `%s` slot %s ↔ orig %s trusted=%s extra=%s ev=%s %s'
                  % (r['script'], r['slot'], r['orig_row'], r['trusted'], r['extra'],
                     r['ev_extra'], r['items']))
    os.makedirs(os.path.dirname(a.report), exist_ok=True)
    with open(a.report, 'w', encoding='utf-8', newline='\n') as f:
        f.write('\n'.join(md) + '\n')

    print('perf_sync_map: sites %d（replace %d ／ drop %d ／ extra_absent %d）'
          ' ; review %d ; pairs %d ; untrusted %d'
          % (len(sites), stat['replace_slots'], stat['extra_slots'], stat['absent_slots'],
             stat['review_slots'], stat['pairs'], stat['untrusted']))
    print('map : %s' % os.path.relpath(a.emit_map, ROOT))
    print('repr: %s' % os.path.relpath(a.report, ROOT))
    return 0


if __name__ == '__main__':
    sys.exit(main())
