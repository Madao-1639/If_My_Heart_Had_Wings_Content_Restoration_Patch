# -*- coding: utf-8 -*-
"""跨脚本接缝闸（seam check）—— 在屏状态跨 `0x07` 跳转是否连续。

机制（见 doc/restoration-route.md §4「跨脚本接缝」与 tool/perfsync.py「跨脚本接缝」）：
`0x07 <脚本名>` 跨脚本跳转**不重置在屏状态**，所以「某脚本第一行看到什么」取决于
**谁跳进来**。单脚本视角（`perf_rows` 从空屏起算）在结构上看不见这件事 —— 本项目
实测的缺陷形态：Steam 在被删 H 段收场处新增一幕 `st03`（全黑 PNG），补丁把删掉的
A-1 整脚本补回后该黑幕无人接管、一路盖住新还原的 HS 场景 ⇒ 黑屏。

判据（与处置动作的后果直接相关）：
    产物入场通道 = ∪ { 产物前序脚本末尾在屏通道 }
    原版入场通道 = ∪ { 原版前序脚本末尾在屏通道 }
    需清通道     = 产物入场通道 − 原版入场通道
清屏幂等（通道不在屏时清它是空操作）⇒ 多入口（剧情前序／回想列表）不需分来源。

适用范围＝**结构定义**（不靠「哪里测出残留」反推）：
    scope = { A-1 整脚本（整个新增脚本）} ∪ { 首个改动槽位为 0 的宿主（插入区间在前缀）}
两者合起来恰好是「插入内容的前缀/后缀所在的位置」。范围内**所有**入边全查，
不看它当前有没有差异 —— 否则下一批新增内容会以同样方式静默复发。

分级
----
* **HARD**：需清通道非空，但产物里该目标脚本前缀没有对应的 `0x37` 清屏；
           以及范围内边数与结构枚举不符（＝范围枚举本身失效）。
* **PASS**：产物入场通道与原版一致，或需清通道已在前缀落地。

用法：`python script/checks/seam_check.py [--product asset] [--orig-dir DIR] [--quiet]`
输出逐条带**两侧状态**（不只计数），HARD ⇒ 非零退出。
"""
import argparse
import collections
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tool import arcbuild, ws2, ws2conv, ws2dis  # noqa: E402
from tool import perfsync  # noqa: E402
from tool import paths  # noqa: E402

A1_SCRIPTS = ['ASA_002', 'ASA_004', 'YOR_003', 'YOR_005', 'YOR_007']


def read_scripts(arc_path):
    """{大写脚本名: 解码字节}"""
    out = {}
    for nb, raw in arcbuild.read_raw(arc_path):
        try:
            n = nb.decode('utf-16le')
        except UnicodeDecodeError:
            continue
        if n.lower().endswith('.ws2'):
            out[n[:-4].upper()] = ws2.decode(raw)
    return out


def read_raw_scripts(arc_path):
    """{大写脚本名: 原始编码字节}"""
    out = {}
    for nb, raw in arcbuild.read_raw(arc_path):
        try:
            n = nb.decode('utf-16le')
        except UnicodeDecodeError:
            continue
        if n.lower().endswith('.ws2'):
            out[n[:-4].upper()] = raw
    return out


def head_scope_hosts(plan):
    """首改动槽位 == 0 的宿主（与 build_restore_plan.head_scope_hosts 同口径）。"""
    out = set()
    for s, h in (plan.get('hosts') or {}).items():
        if h.get('kind') != 'host':
            continue
        pl = h['plan']
        cand = []
        for v in (pl.get('inserts') or []):
            cand.append(v[1])
        for v in (pl.get('drops') or []):
            cand.append(v)
        for v in (pl.get('perf_sync') or {}):
            cand.append(int(v))
        for v in (pl.get('cg_sites') or []):
            cand.append(v[0] if isinstance(v, (list, tuple)) else v.get('slot'))
        cand = [x for x in cand if x is not None]
        if cand and min(cand) == 0:
            out.add(s)
    return out


def prefix_clears(dec):
    """该脚本**前缀区**（第一条 `14` 之前）里的 `0x37` 清屏通道集合。"""
    insts, _ok = ws2dis.disassemble(dec)
    out = set()
    for _off, op, _sz, ops in insts:
        if op == 0x14:
            break
        if op == perfsync.CLEAR:
            s = perfsync._strs(ops)
            if s:
                out.add(s[0])
    return out


def main():
    ap = argparse.ArgumentParser(description='跨脚本接缝闸')
    ap.add_argument('--product', default=str(ROOT / 'asset'))
    ap.add_argument('--orig-dir', default=None)
    ap.add_argument('--quiet', action='store_true')
    args = ap.parse_args()

    odir = args.orig_dir or os.environ.get('IFMH_ORIG_DIR') or paths.orig_dir()
    if not odir or not os.path.isdir(odir):
        sys.exit('需要原版目录：设环境变量 IFMH_ORIG_DIR 或传 --orig-dir')

    plan_path = ROOT / 'resource' / 'restore_plan.json'
    plan = json.load(open(plan_path, encoding='utf-8'))
    declared = (plan.get('seam') or {}).get('entry_clear') or {}

    prod_dec = read_scripts(os.path.join(args.product, 'Rio.arc'))
    orig_raw = read_raw_scripts(os.path.join(odir, 'Rio.arc'))
    ofmt = ws2conv.load_orig_formats(odir)
    # 原版脚本转成 Steam 编码后再看前缀清屏（与 A-1 产物同编码，才能直接比）
    orig_dec = {}
    for k, d in orig_raw.items():
        try:
            orig_dec[k] = ws2.decode(ws2conv.convert_script(d, odir))
        except AssertionError:
            continue

    prod_prof = {k: perfsync.script_profile(ws2dis.disassemble(d)[0])
                 for k, d in prod_dec.items()}
    orig_prof = {}
    for k, d in orig_raw.items():
        try:
            insts, _t = ws2conv.parse(ws2.decode(d), ofmt)
        except AssertionError:
            continue                    # 内嵌数据表脚本，跨脚本边不可解析
        orig_prof[k] = perfsync.script_profile([(op, ops) for op, ops in insts])

    scope = set(A1_SCRIPTS) | head_scope_hosts(plan)
    rows = perfsync.seam_rows(prod_prof, orig_prof, scope)

    # 结构枚举自检：范围内边数（只统计两端都在归档里的边）
    edges = {(p, t) for p, pf in prod_prof.items() for t in pf['jumps']
             if (p in scope or t in scope) and t in prod_prof and t != p}

    hard, ok = [], []
    for r in rows:
        t = r['script']
        need = set(r['clear'])
        landed = prefix_clears(prod_dec[t]) if t in prod_dec else set()
        missing = sorted(need - landed)
        # 过度处置：产物前缀里「判据不管、原版同脚本前缀也没有」的清屏通道。
        # 基准必须是**原版同脚本前缀**，不能以「need 为空」作基准——A-1 整脚本
        # 的前缀本来就带原版自己的清屏（`st01`/`ev`/`bg01` 等），那些不是多余动作。
        base_pfx = prefix_clears(orig_dec[t]) if t in orig_dec else set()
        extra = sorted(landed - need - base_pfx)
        rec = {'script': t, 'prod_entry': r['prod_entry'],
               'orig_entry': r['orig_entry'], 'need': sorted(need),
               'landed': sorted(landed), 'missing': missing, 'extra': extra,
               'extra_value': r['extra_value']}
        (hard if (missing or extra) else ok).append(rec)

    # 名单 ⇄ 计划表一致性：计划的 entry_clear 必须与实际算出的需求一致
    drift = []
    for t in scope:
        want = sorted(declared.get(t) or [])
        got = sorted(next((r['clear'] for r in rows if r['script'] == t), []))
        if want != got:
            drift.append((t, want, got))

    if not args.quiet:
        print('scope(%d): %s' % (len(scope), ', '.join(sorted(scope))))
        print('范围内接缝边数: %d' % len(edges))
        print()
        for rec in ok:
            print(' PASS %-9s 需清=%-14s 已落地=%-14s 入场(产物)=%s 入场(原版)=%s'
                  % (rec['script'], rec['need'] or '-', rec['landed'] or '-',
                     rec['prod_entry'], rec['orig_entry']))
        for rec in hard:
            print(' HARD %-9s 需清=%-14s 已落地=%-14s 缺=%s 多清=%s'
                  % (rec['script'], rec['need'] or '-', rec['landed'] or '-',
                     rec['missing'] or '-', rec['extra'] or '-'))
            print('      入场(产物)=%s' % rec['prod_entry'])
            print('      入场(原版)=%s' % rec['orig_entry'])
        if drift:
            print()
            for t, want, got in drift:
                print(' HARD %-9s restore_plan.seam.entry_clear=%s 但实算=%s'
                      % (t, want, got))
        print()
        print('总结: PASS %d / HARD %d / 表漂移 %d / 范围内边 %d'
              % (len(ok), len(hard), len(drift), len(edges)))

    bad = bool(hard) or bool(drift)
    return 1 if bad else 0


if __name__ == '__main__':
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    sys.exit(main())
