"""承载图 v2：多锚点（语音/CG/跳转/调用）保序对齐 + 双向缺口处理。

相对 v1 的两处修正：
  1. **锚点从 1 类扩到 4 类**（语音名 / `\\x33` 的 PNG 名 / `\\x07` 跳转目标 / `\\x04` 调用名，
     剔除 LAYER_ORDER 等通用名），用 difflib 在**token 序列**上求保序匹配。
  2. **缺口双向对齐**：脚本**头部**缺口按"尾对齐"（多出的原版行在头部 ⇒ 删除）、
     **尾部**缺口按"头对齐"、**中部**缺口若两侧条数不等则标 `ambiguous`（不猜），
     避免 v1 把 `YOR_004` 的头部删除错配到中部。

产出 `resource/carrier_map.json` + `tmp/carrier_map.md`（含 `YOR_004`/`AGE_006` 真值校验）。
"""
import bisect
import collections
import difflib
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))
from tool import arcbuild, ws2, scriptext  # noqa: E402
from tool import paths  # noqa: E402

TOKENS = [
    ('V', re.compile(rb'char[A-Z]{2,4}\x00([A-Za-z0-9_]+\.OGG)\x00', re.I)),
    ('P', re.compile(rb'\x33[A-Za-z0-9_]{2,12}\x00([A-Za-z0-9_.\-]+\.PNG)\x00', re.I)),
    ('J', re.compile(rb'\x07([A-Za-z0-9_]{2,14})\x00')),
    ('C', re.compile(rb'\x04([A-Za-z0-9_]{3,24})\x00')),
]
GENERIC = {'LAYER_ORDER', 'TIMER01', 'CG_ACHIEVEMENT', 'ANIME_ERASE',
           'LOADTIPSCALL', 'EVRET', 'TITLE'}
OUT_JSON = ROOT / 'resource' / 'carrier_map.json'
OUT_MD = ROOT / 'tmp' / 'carrier_map.md'


def load_ws2(arcpath):
    out = {}
    for nb, d in arcbuild.read_raw(arcpath):
        try:
            n = nb.decode('utf-16le')
        except UnicodeDecodeError:
            continue
        if n.lower().endswith('.ws2'):
            out[n[:-4].upper()] = d
    return out


def row_offsets(name, raw):
    rows = [r for r in scriptext.script_rows(name, raw) if r['kind'] in ('dlg', 'ctrl')]
    return [r['off'] for r in rows]


def tokens_of(dec):
    """[(offset, type, value)]，按偏移序，剔除通用名。"""
    out = []
    for t, rx in TOKENS:
        for m in rx.finditer(dec):
            v = m.group(1).decode('ascii', 'replace').upper()
            if v in GENERIC:
                continue
            out.append((m.start(), t, v))
    out.sort()
    return out


def align(name, oraw, sraw):
    o_off = row_offsets(name, oraw)
    s_off = row_offsets(name, sraw)
    o_tok = tokens_of(ws2.decode(oraw))
    s_tok = tokens_of(ws2.decode(sraw))

    def voice_by_row(tok, rows_off):
        """{行号: 语音名}——token 归其后的第一条行（与行归属口径一致）。"""
        out = {}
        for off, t, v in tok:
            if t != 'V':
                continue
            r = bisect.bisect_right(rows_off, off)
            if r < len(rows_off) and r not in out:
                out[r] = v
        return out

    o_voice = voice_by_row(o_tok, o_off)
    s_voice = voice_by_row(s_tok, s_off)

    def content_check(o0, s0, n):
        """1:1 逐位配对的**内容面核对**：两侧语音号都存在且不同 ⇒ 存疑。

        语音号是强身份锚点：两侧同一行却用不同录音，说明 Steam 改写过该行
        （实测这类行 Steam 侧语音号是 Steam 自有号段 `*_6xxx`／`HIT_04xx`）。
        这类块**不得当作 1:1 承载**，须进判读面（见 doc/lessons-learned.md §14／§16）。
        """
        bad = []
        for k in range(n):
            a, b = o_voice.get(o0 + k), s_voice.get(s0 + k)
            if a and b and a != b:
                bad.append({'orig_row': o0 + k, 'steam_slot': s0 + k,
                            'orig_voice': a, 'steam_voice': b})
        return bad

    def mark_1to1(blk, o0, s0, n):
        bad = content_check(o0, s0, n)
        if bad:
            blk['content_suspect'] = bad
            blk['form'] = '1:1（内容存疑：两侧语音号不一致）'
        return blk

    sm = difflib.SequenceMatcher(a=[f'{t}:{v}' for _, t, v in o_tok],
                                 b=[f'{t}:{v}' for _, t, v in s_tok], autojunk=False)
    raw_anchors = []
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == 'equal':
            for k in range(i2 - i1):
                oo = o_tok[i1 + k][0]
                so = s_tok[j1 + k][0]
                # token 归属于其后的第一条行
                orow = bisect.bisect_right(o_off, oo)
                srow = bisect.bisect_right(s_off, so)
                if orow < len(o_off) and srow < len(s_off):
                    raw_anchors.append((orow, srow))

    # 去重 + 保序（同 row 只留最早出现的；保证两序列都严格递增）
    anchors, lo, ls = [], -1, -1
    for a, b in raw_anchors:
        if a > lo and b > ls:
            anchors.append((a, b))
            lo, ls = a, b

    R, K = len(o_off), len(s_off)
    blocks = []

    def gap(o0, o1, s0, s1, where):
        no, ns = o1 - o0, s1 - s0
        if no == 0 and ns == 0:
            return
        if no == ns:
            blocks.append(mark_1to1({'kind': 'match', 'orig': [o0, o1 - 1],
                                     'steam': [s0, s1 - 1], 'form': '1:1',
                                     'anchor': '（区间内无锚点，条数相等）'}, o0, s0, no))
            return
        if no > ns:
            extra = no - ns
            if where == 'head':          # 头部缺口：多出的原版行在**头部** ⇒ 删除
                blocks.append({'kind': 'orig_only', 'orig': [o0, o0 + extra - 1],
                               'form': f'删除候选（头部缺口，{extra} 行）'})
                blocks.append(mark_1to1({'kind': 'match', 'orig': [o0 + extra, o1 - 1],
                                         'steam': [s0, s1 - 1], 'form': '1:1（尾对齐）'},
                                        o0 + extra, s0, ns))
            elif where == 'tail':        # 尾部缺口：多出的原版行在**尾部** ⇒ 删除
                blocks.append(mark_1to1({'kind': 'match', 'orig': [o0, o0 + ns - 1],
                                         'steam': [s0, s1 - 1], 'form': '1:1（头对齐）'},
                                        o0, s0, ns))
                blocks.append({'kind': 'orig_only', 'orig': [o0 + ns, o1 - 1],
                               'form': f'删除候选（尾部缺口，{extra} 行）'})
            else:
                blocks.append({'kind': 'ambiguous', 'orig': [o0, o1 - 1], 'steam': [s0, s1 - 1],
                               'form': f'中部缺口：原版多 {extra} 行，位置待定（需逐段读）'})
        else:
            extra = ns - no
            if where == 'head':
                blocks.append({'kind': 'steam_only', 'steam': [s0, s0 + extra - 1],
                               'form': f'Steam 自写候选（头部缺口，{extra} 格）'})
                blocks.append(mark_1to1({'kind': 'match', 'orig': [o0, o1 - 1],
                                         'steam': [s0 + extra, s1 - 1], 'form': '1:1（尾对齐）'},
                                        o0, s0 + extra, no))
            elif where == 'tail':
                blocks.append(mark_1to1({'kind': 'match', 'orig': [o0, o1 - 1],
                                         'steam': [s0, s0 + no - 1], 'form': '1:1（头对齐）'},
                                        o0, s0, no))
                blocks.append({'kind': 'steam_only', 'steam': [s0 + no, s1 - 1],
                               'form': f'Steam 自写候选（尾部缺口，{extra} 格）'})
            else:
                blocks.append({'kind': 'ambiguous', 'orig': [o0, o1 - 1], 'steam': [s0, s1 - 1],
                               'form': f'中部缺口：Steam 多 {extra} 格，位置待定（需逐段读）'})

    co, cs = 0, 0
    for idx, (oa, sa) in enumerate(anchors):
        where = 'head' if idx == 0 else 'mid'
        gap(co, oa, cs, sa, where)
        blocks.append(mark_1to1({'kind': 'anchor', 'orig': [oa, oa], 'steam': [sa, sa]},
                                oa, sa, 1))
        co, cs = oa + 1, sa + 1
    gap(co, R, cs, K, 'tail')

    return {'script': name, 'orig_rows': R, 'steam_slots': K,
            'orig_tokens': len(o_tok), 'steam_tokens': len(s_tok),
            'anchors': len(anchors), 'blocks': blocks}


def summarize(r):
    dele = sum(b['orig'][1] - b['orig'][0] + 1 for b in r['blocks'] if b['kind'] == 'orig_only')
    add = sum(b['steam'][1] - b['steam'][0] + 1 for b in r['blocks'] if b['kind'] == 'steam_only')
    amb_o = sum(b['orig'][1] - b['orig'][0] + 1 for b in r['blocks']
                if b['kind'] == 'ambiguous' and b['orig'])
    amb_s = sum(b['steam'][1] - b['steam'][0] + 1 for b in r['blocks']
                if b['kind'] == 'ambiguous' and b['steam'])
    anchored = r['anchors']
    return dele, add, amb_o, amb_s, anchored


def main():
    o = load_ws2(Path(paths.orig_dir()) / 'Rio.arc')
    s = load_ws2(Path(paths.STEAM) / 'Rio.arc')
    shared = sorted(set(o) & set(s))

    result = {name: align(name, o[name], s[name]) for name in shared}
    OUT_JSON.write_text(json.dumps(result, ensure_ascii=False, indent=1), 'utf-8')

    tot = collections.Counter()
    L = ['# 承载图 v2（多锚点保序对齐）', '',
         '- 锚点 = 语音名 / CG PNG 名 / 跳转目标 / 调用名（剔除通用名）', '',
         '| 脚本 | 原版行 | Steam槽 | token | 锚点 | 删除候选 | 自写候选 | 待定(原/Steam) |',
         '|---|---:|---:|---:|---:|---:|---:|---|']
    rows_out = []
    for name in shared:
        r = result[name]
        dele, add, ao, as_, an = summarize(r)
        for k, v in (('dele', dele), ('add', add), ('ao', ao), ('as', as_),
                     ('an', an), ('orig', r['orig_rows'])):
            tot[k] += v
        if dele or add or ao or as_:
            rows_out.append((name, r, dele, add, ao, as_))
    for name, r, dele, add, ao, as_ in sorted(rows_out, key=lambda x: -(x[2] + x[4])):
        L.append(f"| {name} | {r['orig_rows']} | {r['steam_slots']} | {r['orig_tokens']} | "
                 f"{r['anchors']} | {dele} | {add} | {ao} / {as_} |")
    L += ['', '## 合计', '',
          f"- 原版行 {tot['orig']}；锚点 {tot['an']} 个",
          f"- 删除候选 {tot['dele']} 行；自写候选 {tot['add']} 格；**待定** 原版 {tot['ao']} 行 / Steam {tot['as']} 格"]

    L += ['', '## 真值校验', '',
          '| 脚本 | 期望 | 实测 | 结论 |', '|---|---|---|---|']
    for name, exp, key in [('YOR_004', '原版 0–84 为删除候选', None),
                           ('AGE_006', '原版 286–304 区间为删除/待定', None)]:
        r = result.get(name)
        if not r:
            continue
        dele, add, ao, as_, an = summarize(r)
        blocks = [b for b in r['blocks'] if b['kind'] != 'anchor' and
                  (b['kind'] != 'match' or '无锚点' in b.get('anchor', ''))]
        head = blocks[0] if blocks else None
        L.append(f"| {name} | {exp} | 删除 {dele} / 自写 {add} / 待定 {ao}·{as_} | 见下 |")
    L.append('')

    for name in ('YOR_004', 'AGE_006'):
        r = result.get(name)
        if not r:
            continue
        L.append(f'### {name} 分块（仅列非 1:1 块与前后邻接）')
        L.append('')
        L.append('| 块 | 原版区间 | Steam区间 | 形态 |')
        L.append('|---|---|---|---|')
        for i, b in enumerate(r['blocks']):
            interesting = (b['kind'] in ('orig_only', 'steam_only', 'ambiguous')
                           or b.get('form', '').startswith(('压缩', '展开')))
            if not interesting:
                continue
            o_ = f"{b['orig'][0]}–{b['orig'][1]}" if b.get('orig') else '—'
            s_ = f"{b['steam'][0]}–{b['steam'][1]}" if b.get('steam') else '—'
            L.append(f"| {b['kind']} | {o_} | {s_} | {b.get('form', '')} |")
        L.append('')

    OUT_MD.write_text('\n'.join(L) + '\n', 'utf-8')
    print('scripts', len(shared), 'orig', tot['orig'], 'anchors', tot['an'],
          'dele', tot['dele'], 'add', tot['add'], 'amb', tot['ao'], '/', tot['as'])


if __name__ == '__main__':
    main()
