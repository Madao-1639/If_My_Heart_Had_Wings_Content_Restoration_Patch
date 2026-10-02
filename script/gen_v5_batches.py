# -*- coding: utf-8 -*-
"""生成 V-5/V-6 判读证据文件（tmp/v5_batches/{SCRIPT}.md）与判读队列（tmp/v5_queue.md）。

只读。块区间沿用承载图的闭区间 [start, end]；行索引 = dlg/ctrl 行、0 起。
判读标准：doc/restoration-targets.md「判定标准：差分形态与采用口径」。
交付：tmp/v5_deliveries/{SCRIPT}.jsonl（每块一行 JSON），校验：script/check_adjudication.py。
控制台只输出 ASCII；日文/中文一律写 UTF-8 文件。
"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
from tool import v5lib  # noqa: E402

OUT_DIR = os.path.join(ROOT, 'tmp', 'v5_batches')
QUEUE = os.path.join(ROOT, 'tmp', 'v5_queue.md')

# 判读优先级（T0 校准批带已知答案；T4 = 其余，由生成器自动归入）
TIER = {}
for s in ('YOR_004', 'AGE_006'):
    TIER[s] = 'T0'
for s in ('AGE_005', 'AGE_007', 'AGE_010', 'AMA_004', 'AMA_006', 'AMA_007',
          'AMA_010', 'KOT_003', 'KOT_006', 'KOT_009'):
    TIER[s] = 'T1'
for s in ('ASA_001', 'ASA_003', 'YOR_002', 'YOR_006', 'ASA_005', 'AMA_005',
          'AGE_011', 'AGE_008', 'YOR_008', 'KOT_004', 'AMA_008'):
    TIER[s] = 'T2'
for s in ('AGE_001', 'AGE_009'):
    TIER[s] = 'T3'
TIER_NAME = {'T0': 'T0 校准', 'T1': 'T1 A-2 H本体', 'T2': 'T2 L2出入口',
             'T3': 'T3 L3擦边', 'T4': 'T4 其余'}

TRIM_HEAD, TRIM_TAIL, TRIM_KEEP = 15, 10, 30  # 块内行数 > TRIM_KEEP 时掐中段


def fmt(t):
    return (t or '').replace('\n', ' / ')


def orig_texts(script):
    """优先 resource/corpus/jp（带说话人）；不可用则回退 ws2 行文本。统一归一化为字符串列表。"""
    t = v5lib.jp_texts(script)
    if t is not None:
        return [(x.get('text_with_name') or x['text']) for x in t], True
    return [r['jp'] for r in v5lib.rows('orig', script)], False


def cell_text_e(script, i):
    rl = v5lib.rows('steam', script)
    return rl[i]['jp'] if 0 <= i < len(rl) else None


def cell_text_z(script, i):
    z = v5lib.zh_official(script)
    return z[i] if z and 0 <= i < len(z) else None


def voice_mark(voice, side):
    if not voice:
        return ''
    if side == 'orig':
        return voice + ('' if v5lib.voice_in_steam(voice) else ' 【Steam缺】')
    mark = '' if v5lib.voice_in_orig(voice) else ' 【原版缺】'
    return voice + mark


def png_mark(png, side):
    if not png:
        return ''
    if side == 'orig':
        return png + ('' if v5lib.png_in_steam(png) else ' 【Steam缺】')
    return png


def render_rows(lines, script, lo, hi, tok, side, otexts):
    """行表（含掐中段）。闭区间 [lo, hi]。otexts = (文本列表, 是否 jp json)。"""
    idxs = list(range(lo, hi + 1))
    if len(idxs) > TRIM_KEEP:
        shown = idxs[:TRIM_HEAD] + [None] + idxs[-TRIM_TAIL:]
    else:
        shown = idxs
    texts, is_jp = otexts
    rl = v5lib.rows(side, script)
    for i in shown:
        if i is None:
            lines.append('| …… | （省略 %d 行） | | |' % (len(idxs) - TRIM_HEAD - TRIM_TAIL))
            continue
        kind = rl[i]['kind'] if i < len(rl) else '?'
        if side == 'orig':
            t = texts[i] if i < len(texts) else '(缺)'
            v, p = tok[i]
            lines.append('| %d%s | %s | %s | %s |' % (
                i, '（ctrl）' if kind == 'ctrl' else '', fmt(t),
                voice_mark(v, side), png_mark(p, side)))
        else:
            t = rl[i]['jp'] if i < len(rl) else '(缺)'
            v, p = tok[i]
            lines.append('| %d%s | %s | %s | %s |' % (
                i, '（ctrl）' if kind == 'ctrl' else '', fmt(t),
                voice_mark(v, side), png_mark(p, side)))


def render_block(lines, script, bi, blk, nblk):
    kind = blk['kind']
    o = blk.get('orig')
    s = blk.get('steam')
    o0, o1 = (o if o else (-1, -2))
    s0, s1 = (s if s else (-1, -2))
    head = '## 块 %d/%d · %s · 原版 %s · Steam %s' % (
        bi, nblk, kind,
        ('%d–%d' % (o0, o1)) if o1 >= o0 else '（无）',
        ('%d–%d' % (s0, s1)) if s1 >= s0 else '（无）')
    lines += ['', head, '', '- 承载图判定：%s' % blk.get('form', '')]
    lines.append('- ledger 头（照抄）：`{"script":"%s","block_orig":[%d,%d],"block_steam":[%d,%d],`'
                 % (script, o0, o1, s0, s1))
    # 前文 / 后文 1:1 上下文（各 2 行）
    otexts = orig_texts(script)
    o_ctx = otexts[0]
    for title, lo, hi in (('前文（1:1 上下文）', o0 - 2, o0 - 1), ('后文（1:1 上下文）', o1 + 1, o1 + 2)):
        seg = [x for x in range(lo, hi + 1) if 0 <= x < len(o_ctx)]
        if seg:
            lines += ['', '### %s（原版侧）' % title, '', '| 行 | 文本 |', '|---:|---|']
            for i in seg:
                lines.append('| %d | %s |' % (i, fmt(o_ctx[i])))
    # 原版侧
    if o1 >= o0:
        tok = v5lib.row_tokens('orig', script)
        lines += ['', '### 原版侧（块内，语音列标【Steam缺】= 该录音 Steam 全表无锚点）', '',
                  '| 行 | 文本 | 语音 | 图片 |', '|---:|---|---|---|']
        render_rows(lines, script, o0, o1, tok, 'orig', otexts)
    # Steam 侧
    if s1 >= s0:
        tok = v5lib.row_tokens('steam', script)
        z = v5lib.zh_official(script)
        lines += ['', '### Steam 侧（块内，语音列标【原版缺】= 该录音不在原版，`_6xxx` 即 Steam 自录）', '',
                  '| 槽 | 文本(英文) | 官方zh | 语音 | 图片 |', '|---:|---|---|---|---|']
        idxs = list(range(s0, s1 + 1))
        shown = idxs  # Steam 侧是判定目标，永不掐中段
        rl = v5lib.rows('steam', script)
        for i in shown:
            if i is None:
                lines.append('| …… | （省略 %d 格） | | | |' % (len(idxs) - TRIM_HEAD - TRIM_TAIL))
                continue
            kind = rl[i]['kind'] if i < len(rl) else '?'
            ze = cell_text_z(script, i) or '（无官方zh）'
            v, p = tok[i] if i < len(tok) else (None, None)
            lines.append('| %d%s | %s | %s | %s | %s |' % (
                i, '（ctrl）' if kind == 'ctrl' else '', fmt(rl[i]['jp'] if i < len(rl) else ''),
                fmt(ze), voice_mark(v, 'steam'), png_mark(p, 'steam')))
        if z is not None and len(z) != len(rl):
            lines += ['', '> 注意：官方 zh %d 条 vs Steam 槽 %d（U-10，尾部可能偏移）。' % (len(z), len(rl))]
    lines.append('')
    lines.append('---')


def worklist():
    out = []
    for s in v5lib.scripts_with_blocks():
        out.append((s, TIER.get(s, 'T4')))
    order = {'T0': 0, 'T1': 1, 'T2': 2, 'T3': 3, 'T4': 4}
    out.sort(key=lambda x: (order[x[1]], x[0]))
    return out


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    qlines = ['# V-5/V-6 判读队列', '',
              '> 顺序即派单优先级。状态：待判 / 已交付（tmp/v5_deliveries/） / 已落地（resource/adjudication/）。',
              '> 每个脚本一份证据文件 tmp/v5_batches/{SCRIPT}.md；判读标准 = '
              'doc/restoration-targets.md「判定标准：差分形态与采用口径」。', '',
              '| # | 脚本 | 层 | amb块 | 原版行 | oo块 | 原版行 | so块 | Steam格 | 状态 |',
              '|---:|---|---|---:|---:|---:|---:|---:|---:|---|']
    n = 0
    total_amb = total_oo = total_so = 0
    for s, tier in worklist():
        blks = v5lib.blocks(s)
        amb = [b for b in blks if b['kind'] == 'ambiguous']
        oo = [b for b in blks if b['kind'] == 'orig_only']
        so = [b for b in blks if b['kind'] == 'steam_only']
        amb_o = sum(b['orig'][1] - b['orig'][0] + 1 for b in amb if b.get('orig'))
        oo_o = sum(b['orig'][1] - b['orig'][0] + 1 for b in oo if b.get('orig'))
        so_k = sum(b['steam'][1] - b['steam'][0] + 1 for b in so if b.get('steam'))
        total_amb += len(amb); total_oo += len(oo); total_so += len(so)
        lines = ['# %s — V-5/V-6 判读证据（%s）' % (s, TIER_NAME[tier]), '',
                 '- 判读标准（必读）：doc/restoration-targets.md「判定标准：差分形态与采用口径」',
                 '- 交付：`tmp/v5_deliveries/%s.jsonl`，每块一行 JSON，块头 ranges 照抄。' % s,
                 '- 自检：`$PY script/check_adjudication.py tmp/v5_deliveries/%s.jsonl`' % s,
                 '- 语音列口径：token 归属其后最近一行，无则向前借；存在性来自 res_diff 名单。', '']
        for bi, blk in enumerate(blks, 1):
            render_block(lines, s, bi, blk, len(blks))
        with open(os.path.join(OUT_DIR, s + '.md'), 'w', encoding='utf-8') as f:
            f.write('\n'.join(lines))
        n += 1
        qlines.append('| %d | %s | %s | %d | %d | %d | %d | %d | %d | 待判 |'
                      % (n, s, TIER_NAME[tier], len(amb), amb_o, len(oo), oo_o, len(so), so_k))
    qlines += ['', '合计：脚本 %d，ambiguous 块 %d、orig_only 块 %d、steam_only 块 %d。'
               % (n, total_amb, total_oo, total_so)]
    with open(QUEUE, 'w', encoding='utf-8') as f:
        f.write('\n'.join(qlines))
    print('batches: %d scripts -> %s' % (n, OUT_DIR))
    print('queue: %s' % QUEUE)
    print('blocks: ambiguous %d / orig_only %d / steam_only %d' % (total_amb, total_oo, total_so))


if __name__ == '__main__':
    main()
