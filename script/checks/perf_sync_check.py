# -*- coding: utf-8 -*-
"""演出同步闸（产物 vs 原版，逐槽对账）。

方针（用户 2026-10-10 定案，见 doc/restoration-route.md §7 V-10）：
**与原版相比，每类演出（语音 / CG / 立绘 / 背景）要么两侧同时存在且相等，要么都不存在。**

对齐 = `resource/restore_plan.json` 的 `slot_sources`（产物槽 → steam 槽 / 原版行）
       ＋ `resource/carrier_map.json` 的 anchor/match 等长 1:1 块（steam 槽 → 原版行）。
立绘两版是同一份资源的两套命名（`ST_KOTORI_*` ↔ `A小鳥_*`）⇒ 先归一再比；
背景与 CG 两版同名 ⇒ 按名直接比。

分级
----
* **HARD**：产物侧**多出**原版没有的演出（`extra`）——即本闸要拦的缺陷类；
  以及判定表 `resource/perf_sync_map.json` 的 `action=drop` 条目未逐条落地。
* **REVIEW**：产物侧**缺失**或**取值不同**（`missing` / `different`）——不自动处置，
  逐条列出供人工裁定（其中一部分为承载图假配对或两版素材差异，见表内 `review`）。

用法：`python script/checks/perf_sync_check.py [--product asset] [--orig-dir DIR] [--quiet]`
HARD 级失配 ⇒ 非零退出。
"""
import argparse
import collections
import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tool import arcbuild, ws2, ws2conv, ws2dis  # noqa: E402
from tool import perfsync  # noqa: E402
from tool import paths  # noqa: E402

SPRITE_MAP = perfsync.SPRITE_MAP
norm_sprite = perfsync.norm_sprite
perf_rows = perfsync.perf_rows


def _members(path):
    return {nb.decode('utf-16le', 'replace'): d for nb, d in arcbuild.read_raw(path)}


def _parse_orig(raw, ofmt):
    parsed, _ = ws2conv.parse(ws2.decode(raw), ofmt)
    out, p = [], 0
    for op, ops in parsed:
        out.append((p, op, 1 + len(ops), ops))
        p += 1 + len(ops)
    return out


def _state_images(state):
    """在屏图像 → {归一图名: 通道}（`ev`／`st\\d+`／`bg\\d+`，排除 `bgm`）。"""
    out = {}
    for k, v in state.items():
        if perfsync._is_img_chan(k) and v and not perfsync.is_cg_name(v):
            out[v] = k          # CG 名图不进本闸（无论落在哪个通道）：交 cg_seq_check
    return out


def _image_diff(pa, oa):
    """两快照的在屏图名集合差 → (extra, missing)。

    `extra`＝产物在屏、原版在屏没有的图（缺陷类，`ev` 单列见调用方）；
    `missing`＝原版在屏、产物没有的图。**按图名比，不按通道号**——容忍两版背景
    通道号错位（原版 `bg01` ↔ Steam `bg02`）。
    """
    pi, oi = _state_images(pa), _state_images(oa)
    extra = [(img, pi[img]) for img in sorted(pi) if img not in oi]
    missing = [(img, oi[img]) for img in sorted(oi) if img not in pi]
    return extra, missing


def main(argv=None):
    ap = argparse.ArgumentParser(description='演出同步闸（产物 vs 原版）')
    ap.add_argument('--product', default=str(ROOT / 'asset'))
    ap.add_argument('--backup', default=str(ROOT / 'backup'))
    ap.add_argument('--orig-dir', default=os.environ.get('IFMH_ORIG_DIR', ''))
    ap.add_argument('--quiet', action='store_true')
    ap.add_argument('--max-detail', type=int, default=40)
    ap.add_argument('--out', default=str(ROOT / 'tmp' / 'perf_sync_check.md'))
    args = ap.parse_args(argv)
    if not args.orig_dir or not os.path.isdir(args.orig_dir):
        sys.exit('原版目录未提供：设 --orig-dir 或环境变量 IFMH_ORIG_DIR')
    if not os.path.isdir(args.product):
        sys.exit('产物目录不存在：%s' % args.product)

    ofmt = ws2conv.load_orig_formats(args.orig_dir)
    plan = json.load(open(ROOT / 'resource' / 'restore_plan.json', encoding='utf-8'))
    carrier = json.load(open(ROOT / 'resource' / 'carrier_map.json', encoding='utf-8'))
    pmap = json.load(open(ROOT / 'resource' / 'perf_sync_map.json', encoding='utf-8')) \
        if (ROOT / 'resource' / 'perf_sync_map.json').exists() else {'sites': []}

    prod_rio = _members(os.path.join(args.product, 'Rio.arc'))
    orig_rio = _members(os.path.join(args.orig_dir, 'Rio.arc'))
    steam_rio = _members(os.path.join(args.backup, 'Rio.arc')) \
        if os.path.isdir(args.backup) else {}
    table_slots = collections.defaultdict(set)
    for s0 in pmap.get('sites', []):
        table_slots[s0['script']].add(int(s0['slot']))

    hard, review = [], []
    stat = collections.Counter()

    for script, host in sorted(plan['hosts'].items()):
        if host.get('kind') != 'host':
            continue
        key = script + '.ws2'
        if key not in prod_rio:
            hard.append({'script': script, 'issue': 'absent-in-product'})
            continue
        p_rows = perf_rows(ws2dis.disassemble(ws2.decode(prod_rio[key]))[0])
        o_rows = perf_rows(_parse_orig(orig_rio[key], ofmt))
        # 原版**全脚本**出现过的图名集合：产物在屏的图若在此集合外 ⇒ Steam 新增素材，必属缺陷。
        orig_script_images = set()
        for rw in o_rows:
            orig_script_images |= perfsync.images(rw['eff'])
        # 注：`perfsync.images()` 仍含 CG 名图（供别处用）；本闸的对账走 `_state_images()`
        # （已排掉 CG 名图），见下。
        s2o = perfsync.align_map(script, carrier)
        # 语音号自证：给 `ambiguous` 块里缺对齐的 Steam 槽补映射（与产出端同口径）
        s2o = perfsync.interp_align(perfsync.voice_align(
            [r['own'] for r in perf_rows(ws2dis.disassemble(
                ws2.decode(steam_rio[key]))[0])],
            [r['own'] for r in o_rows], s2o, override=True))
        # 范围＝**脚本级**（只判「内容层被还原动过」的宿主），**不做行级收窄**：演出是延续量，
        # 行级收窄会把分歧的**根**切掉（根槽常落在还原段之外）。与产出端同口径，见
        # doc/restoration-route.md §6 V-10 与 lessons §27。
        setter, setter_hist = {}, []
        for i, (_src, _v) in enumerate(host['plan']['slot_sources']):
            if i >= len(p_rows):
                break
            for chan in (p_rows[i]['own'].get('display') or {}):
                setter[chan] = i
            setter_hist.append(dict(setter))     # 该行当时的设值槽（回溯根槽用**当时**的，不是最终值）
        for i, (src, val) in enumerate(host['plan']['slot_sources']):
            if i >= len(p_rows):
                break
            r = val if src == 'orig' else s2o.get(val)
            if r is None or r >= len(o_rows):
                stat['unaligned'] += 1
                continue
            stat['pairs'] += 1
            pe, oe = p_rows[i]['eff'], o_rows[r]['eff']
            ex, miss = _image_diff(pe, oe)
            hard_ex, soft_ex = [], []
            for img, c in ex:
                # 分类：图名在原版全脚本都不存在（Steam 新增素材）或该图根槽在判定表内
                # （判定表要求删却没删）⇒ HARD；其余（图名原版有、只是位置/时机不同 ⇒
                # 属「原版有、产物未补回」的 missing 方向）⇒ REVIEW。
                root = setter.get(c)
                if c == 'ev':
                    soft_ex.append((img, c))
                elif img not in orig_script_images or (root is not None
                                                       and root in table_slots.get(script, ())):
                    hard_ex.append((img, c))
                else:
                    soft_ex.append((img, c))
            if hard_ex:
                stat['hard'] += 1
                hard.append({'script': script, 'cell': i, 'src': '%s:%s' % (src, val),
                             'orig_row': r, 'extra': ['%s:%s' % (c, img) for img, c in hard_ex],
                             'product_eff': pe, 'orig_eff': oe})
            if soft_ex or miss:
                stat['review'] += 1
                _hist = setter_hist[i] if i < len(setter_hist) else {}
                review.append({'script': script, 'cell': i, 'src': '%s:%s' % (src, val),
                               'orig_row': r,
                               'extra_stale': ['%s:%s@%s' % (c, img, _hist.get(c))
                                               for img, c in soft_ex],
                               'missing': ['%s:%s' % (c, img) for img, c in miss]})

    # 闸：判定表条目必须逐条落地（`plan.gates.perf_sync_*` 之和 ＝ 判定表 sites 数）
    want = sum(1 for s in pmap.get('sites', []) if s.get('action') in ('drop', 'replace'))
    got = sum(v for k, v in plan.get('gates', {}).items() if k.startswith('perf_sync_'))
    stat['table_sites'] = want
    stat['applied_sites'] = got
    table_ok = (want == got and want > 0)
    if not table_ok:
        hard.append({'script': '(table)', 'issue': 'perf_sync 名单未逐条落地',
                     'table_sites': want, 'applied_sites': got})

    lines = ['# 演出同步闸（产物 vs 原版）', '',
             '- 产物 `%s` ｜ 原版 `%s`' % (args.product, args.orig_dir), '',
             '## 读数', '', '| 项 | 值 |', '|---|---|']
    for k, v in sorted(stat.items()):
        lines.append('| %s | %d |' % (k, v))
    lines += ['', '## HARD（产物多出的演出 / 名单未落地）', '']
    for h in hard[:args.max_detail]:
        lines.append('- %s' % json.dumps(h, ensure_ascii=False, sort_keys=True))
    if len(hard) > args.max_detail:
        lines.append('- …（其余 %d 条见 tmp/perf_sync_check.json）' % (len(hard) - args.max_detail))
    lines += ['', '## REVIEW（缺失 / 取值不同，人工裁定）', '']
    for r in review[:args.max_detail]:
        lines.append('- %s' % json.dumps(r, ensure_ascii=False, sort_keys=True))
    if len(review) > args.max_detail:
        lines.append('- …（其余 %d 条见 tmp/perf_sync_check.json）' % (len(review) - args.max_detail))
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, 'w', encoding='utf-8', newline='\n') as f:
        f.write('\n'.join(lines) + '\n')
    with open(ROOT / 'tmp' / 'perf_sync_check.json', 'w', encoding='utf-8', newline='\n') as f:
        json.dump({'hard': hard, 'review': review, 'stat': dict(stat)}, f,
                  ensure_ascii=False, indent=0)
        f.write('\n')

    if not args.quiet:
        print('演出同步：pairs %d ; HARD %d ; REVIEW %d ; 名单 %d / 落地 %d'
              % (stat['pairs'], len(hard), len(review), want, got))
        by = collections.Counter(h['script'] for h in hard)
        for s, n in sorted(by.items()):
            print('  HARD %-12s %d' % (s, n))
        print('report: %s' % args.out)
    return 1 if hard else 0


if __name__ == '__main__':
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    sys.exit(main())
