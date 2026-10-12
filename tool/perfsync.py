# -*- coding: utf-8 -*-
"""演出同步（演出状态对账）共享库 —— 产出端脚本与闸共用同一套判据。

方针（用户 2026-10-10 定案，见 doc/restoration-route.md §7 V-10）：
**与原版相比，每类演出（语音 / CG / 立绘 / 背景）要么两侧同时存在且相等，要么都不存在。**

两版命名差异
------------
* **立绘**：同一份资源的两套命名（Steam `ST_KOTORI_02L.PNA` ↔ 原版 `A小鳥_02L.PNA`，
  PNA 逐层结构一致）⇒ 比之前先归一（`norm_sprite`）。
* **背景**：文件两版同名（实测 `BG*` 两版归档皆有），但**通道号可能不同**
  （原版 `bg01` ↔ Steam `bg02`，Steam 用 `bg01` 放 CG 替身）⇒ 判「多不多」按
  **在屏图名集合**，不按通道号。
* **CG**（`ev` 通道）：同名；CG 序列另有 `script/checks/cg_seq_check.py` 专管，
  本库把 `ev` 的差异一律降为 `review`，不自动处置。

own / eff
---------
* `own`＝该槽**自带**的演出（该槽 `0x14` 之前、上一条 `0x14` 之后的指令）。
* `eff`＝该槽读到时**在屏**的演出（含前一格延续；语音/画面都是延续语义，
  见 doc/file-formats.md「格内指令的归属次序」）。
"""
import json
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

SPRITE_MAP = {
    'ST_KOTORI': 'A小鳥', 'ST_AGEHA': 'Bあげは', 'ST_AMANE': 'C天音',
    'ST_ASA': 'D亜紗', 'ST_YORU': 'E夜瑠', 'ST_HIBARI': 'Fひばり',
    'ST_HOTARU': 'Gほたる', 'ST_AKARI': 'H朱莉', 'ST_KANAKO': 'I佳奈子',
    'ST_TATUYA': 'J達也', 'ST_MASATUGU': 'K柾次', 'ST_KUJIRA': 'L鯨',
    'ST_AOI': 'M碧', 'ST_ISUKA': 'Nイスカ', 'ST_SANAE': 'O早苗',
    'ST_RYOKO': 'P亮子', 'ST_YUKA': 'Q由佳', 'ST_HAT': 'Rハット',
    'ST_TAKAO': 'S隆夫',
}

_STR_RX = re.compile(rb'[\x20-\x7e\x80-\xff]{1,}\x00')
DISPLAY = (0x33, 0x34)
CLEAR = 0x37
VOICE = 0x28
BGM = 0x1E
ROW = 0x14


def _strs(ops):
    out = []
    for m in _STR_RX.finditer(ops):
        try:
            t = m.group(0)[:-1].decode('cp932')
        except UnicodeDecodeError:
            continue
        if any(c.isalnum() or ord(c) > 0x2000 for c in t):
            out.append(t)
    return out


def norm_sprite(name):
    """立绘名归一：Steam `ST_<ROLE>_<pose>` → 原版 `<角色码>_<pose>`。"""
    if not name:
        return name
    m = re.match(r'^(ST_[A-Z]+)_(.*)$', name, re.I)
    if m:
        base = SPRITE_MAP.get(m.group(1).upper())
        if base:
            return base + '_' + m.group(2)
    return name


def perf_rows(instrs):
    """逐 `14` 槽 → {'own': {...}, 'eff': {...}}。

    `own` 只含本槽自带演出；`eff` 为含延续的末值（`ev`／`st*`／`bg*`／`bgm` 延续，
    `voice` 逐行）。显示值为**归一后**的图名。
    """
    state, rows, own, voice = {}, [], {}, []
    for _off, op, _sz, ops in instrs:
        s = _strs(ops)
        if op in DISPLAY and len(s) >= 2:
            chan, name = s[0], norm_sprite(s[1])
            own.setdefault('display', {})[chan] = name
            state[chan] = name
        elif op == CLEAR and s:
            own.setdefault('clear', set()).add(s[0])
            (own.get('display') or {}).pop(s[0], None)   # 同前缀内「设后即清」⇒ 净效果为无
            state.pop(s[0], None)
        elif op == BGM and s:
            own.setdefault('bgm', []).append(s[0])
            state['bgm'] = s[0]
        elif op == VOICE and len(s) >= 2:
            if s[0].lower().startswith('char'):
                v = [x for x in s if x.upper().endswith('.OGG')]
                if v:
                    voice = v
                    own['voice'] = v
            else:
                own.setdefault('se', []).append(s[1])
        elif op == ROW:
            eff = dict(state)
            eff['voice'] = voice
            rows.append({'own': own, 'eff': eff})
            own, voice = {}, []
    return rows


def _is_img_chan(chan):
    r"""图像类通道：`ev`／`st\d+`／`bg\d+`（排除 `bgm`）。"""
    return chan == 'ev' or bool(re.match(r'^(st|bg)\d', chan))


# 路线/场景代码（= Rio.arc 脚本名前缀）；与 script/checks/cg_seq_check.py 的 `ROUTES` 同源。
ROUTES = {'AGE', 'AMA', 'ASA', 'CO1', 'CO2', 'HUT', 'KOT', 'YOR'}
_CG_RX = re.compile(r'^[A-Z]{3}_\d{2,4}(_\d{2,4}[A-Z]?)?\.PNG$')


def is_cg_name(name):
    """图名是不是 **CG** —— 权威口径与 `script/checks/cg_seq_check.py::is_cg` 完全一致
    （用户 2026-10-08 明确）：CG ＝ 名字形如 `{路线名}_{编号}`（`AGE_06_001S`、`KOT_12_003B`）；
    其余（`BG*`／`SKY*`／`EST_*`／`CUTIN_*`／`COM_*`／`ST*`／`IMD*`／`MOS*`）是**其他素材**。

    ⚠️ **为什么判据要按「图名」而不是「通道名」**：Steam 会把**第二张 CG 塞进 `bg` 通道**
    （B→S 交叉淡入的那一层），于是通道名会说谎——按通道判会把 CG 层当「背景」删掉/换掉，
    既破坏 CG 序列，又让 `cg_seq_check` 报出本不该有的缺口（2026-10-10 实测 `KOT_003` s1072
    的 `bg02=KOT_12_003S`）。**CG 一律归 `cg_seq_check` + `cg_site_rewrites.json` 管，
    本机制不碰**（无论它落在哪个通道）。
    """
    if not name:
        return False
    u = name.upper()
    return u.split('_')[0] in ROUTES and bool(_CG_RX.match(u))


def sb_chan(chan, name):
    """是不是本机制该管的**立绘/背景**通道：`st*`/`bg*` 且图名**不是 CG**。"""
    return (chan.startswith('st') or chan.startswith('bg')) and not is_cg_name(name)


# 显示块的图层伴生操作码：`39` 建层、`04 LAYER_ORDER` 调用、`09` 图层权重、
# `46` 图层定位、`3e`/`65` 块尾标记；显示指令本身为 `33`/`34`，前置 `64`。
# `0b`（布尔状态写入）夹在块内时**属块的一段**（块要连续扫过去），但**不随块搬运**
# ——写入是状态、不是演出，删块时保留、补块时不重复写。
BLOCK_OPS = {0x09, 0x0B, 0x39, 0x3E, 0x46, 0x65}
BLOCK_MOVE_SKIP = {0x0B}


def _is_layer_order(op, ops):
    return op == 0x04 and ops.split(b'\x00')[0] == b'LAYER_ORDER'


def _str_at(ops):
    """操作数首个 NUL 定界字符串（cp932）。"""
    s = _strs(ops)
    return s[0] if s else None


def image_blocks(instrs):
    """某行**前缀区**（`[(op, ops), ...]`）内的图像演出块，按原顺序。

    返回 `[{'kind':'display'|'clear', 'chan':str, 'name':str|None, 'idx':[下标]}]`：
    `display` 块＝显示指令（`33`/`34`，图像通道）＋其后连续的图层伴生
    （`39`/`04 LAYER_ORDER`/`09`/`46`/`3e`/`65`），前置 `64` 一并带上；
    `clear` 块＝`37 <图像通道>`。
    """
    out, j, n = [], 0, len(instrs)
    while j < n:
        op, ops = instrs[j][0], instrs[j][1]
        s = _strs(ops)
        if op in DISPLAY and len(s) >= 2 and _is_img_chan(s[0]):
            lo = j
            if lo - 1 >= 0 and instrs[lo - 1][0] == 0x64:
                lo -= 1
            k = j + 1
            while k < n and (instrs[k][0] in BLOCK_OPS or _is_layer_order(*instrs[k][:2])):
                k += 1
            out.append({'kind': 'display', 'chan': s[0], 'name': s[1],
                        'idx': list(range(lo, k))})
            j = k
        elif op == CLEAR and s and _is_img_chan(s[0]):
            out.append({'kind': 'clear', 'chan': s[0], 'name': None, 'idx': [j]})
            j += 1
        else:
            j += 1
    return out


def row_instrs(instrs):
    """逐 `14` 槽的前缀区指令列表（`[(op, ops), ...]`，不含 `14` 自身）。

    归属口径与 `perf_rows` 一致：**上一条 `14` 之后 → 本槽 `14` 之前**的指令属本槽。
    """
    rows, cur = [], []
    for ins in instrs:
        if ins[1] == ROW:
            rows.append(cur)
            cur = []
        else:
            cur.append((ins[1], ins[3]))
    return rows


def images(state):
    """在屏/自带的图名集合（归一后），不含 `bgm`／`voice`。"""
    return {v for k, v in state.items() if _is_img_chan(k)}


def ev_name(state):
    return state.get('ev')


def classify(prod_own, prod_eff, orig_eff):
    """本槽自带演出 vs 原版对齐行的**在屏**演出 → (extra, review, ev_extra)。

    * `extra`：本槽自带的 `st*`／`bg*` 显示是**多余演出**（原版在屏没有这张图），删。
      判据（容忍两版**通道号错位**，如原版 `bg01` ↔ Steam `bg02`）：
        图名 ∉ 原版在屏图名集合 ∧（原版该通道没有图 ∨ 原版该通道那张图在产物**别处**
        仍在屏）——后一条把「通道号错位、原图仍在屏」与「原版该通道是**另一张图**且
        产物没有」区分开：前者本图多余（删），后者属**取值不同**（不删，登记 review）。
    * `review`：其余差异（原版该通道是另一张图且产物没有 = different；原版在屏有、
      产物没有 = missing），逐条登记供人工裁定，不自动处置。
    * `ev_extra`：`ev` 通道的多余显示单列（CG 序列另有 `cg_seq_check.py` 专管）。
    """
    o_img = images(orig_eff)
    p_img = images(prod_eff)
    extra, review, ev_extra = [], [], []
    for chan, name in sorted((prod_own.get('display') or {}).items()):
        if name in o_img:
            continue                                  # 原版在屏也有这张图 ⇒ 不多余
        if sb_chan(chan, name):                       # `st*`/`bg*` 且**图名不是 CG**
            if chan not in orig_eff or orig_eff[chan] in p_img:
                extra.append(chan)
            else:
                review.append({'kind': 'different', 'chan': chan,
                               'prod': name, 'orig': orig_eff.get(chan)})
        elif chan == 'ev':
            ev_extra.append(chan)
        # 其余（`st*`/`bg*` 通道但**图名是 CG**）不进本机制：CG 归 cg_seq_check 管
    for chan in sorted(set(orig_eff) - set(prod_eff)):
        if _is_img_chan(chan) and orig_eff[chan] not in p_img:
            review.append({'kind': 'missing', 'chan': chan,
                           'prod': None, 'orig': orig_eff[chan]})
    return sorted(extra), review, sorted(ev_extra)


_QUIRKS = None


def _quirks():
    global _QUIRKS
    if _QUIRKS is None:
        p = os.path.join(ROOT, 'resource', 'carrier_quirks.json')
        out = {}
        if os.path.exists(p):
            for x in json.load(open(p, encoding='utf-8')).get('quirks', []):
                if x.get('kind') not in ('false_anchor', 'missing_seam'):
                    continue
                s = (x.get('mechanical') or {}).get('steam') or []
                if len(s) != 2:
                    continue
                out.setdefault(x['script'], set()).update(range(s[0], s[1] + 1))
        _QUIRKS = out
    return _QUIRKS


_ALIGN_FIX = None


def align_fixes():
    """`resource/align_fixes.json` —— 人工定案的逐槽对齐 → `{(脚本, steam 槽): 原版行|None}`。

    残余对齐评审的落地形态：机械可判的（承载图 anchor/match、语音自证、1:1 内插）不入本表；
    只有「承载图给不出映射 ∧ 语音自证失败 ∧ 缺口非 1:1」的槽才由人工定案写在这里。
    `None` ＝ 该槽无对应原版行（Steam 自写）⇒ 从对齐来源剔除。
    """
    global _ALIGN_FIX
    if _ALIGN_FIX is None:
        p = os.path.join(ROOT, 'resource', 'align_fixes.json')
        out = {}
        if os.path.exists(p):
            for sc, m in (json.load(open(p, encoding='utf-8')).get('fixes') or {}).items():
                for k, r in m.items():
                    out[(sc, int(k))] = (None if r is None else int(r))
        _ALIGN_FIX = out
    return _ALIGN_FIX


def align_map(script, carrier):
    """Steam 槽 → 原版行：承载图 `anchor`/`match` **等长**块线性内插。

    **剔除已知假锚/漏缝**：`resource/carrier_quirks.json` 里 `kind ∈ {false_anchor,
    missing_seam}` 的机械配对不得用作演出同步的对齐来源——机械配错会把**别的行**的演出
    搬过来（2026-10-10 演出同步评审实证：AGE_005 s128、AMA_010 s277）。
    **人工定案优先**：`resource/align_fixes.json` 的条目覆盖推断值（`null` ＝ 剔除）。
    """
    s2o = {}
    for b in carrier[script]['blocks']:
        if b['kind'] not in ('anchor', 'match'):
            continue
        o, s = b.get('orig'), b.get('steam')
        if not o or not s or (o[1] - o[0]) != (s[1] - s[0]):
            continue
        for k in range(s[1] - s[0] + 1):
            s2o[s[0] + k] = o[0] + k
    for k in _quirks().get(script, ()):
        s2o.pop(k, None)
    for (sc, k), r in align_fixes().items():
        if sc != script:
            continue
        if r is None:
            s2o.pop(k, None)
        else:
            s2o[k] = r
    return s2o


def voice_align(s_own, o_own, s2o, override=False):
    """按**本槽自带语音号**校正/补齐 Steam 槽 → 原版行的对齐。

    语音号是**自证**的对位信号：整脚本内同号行唯一即可定案，且判定本身即「两侧语音号
    相等」这条可信度判据。两种用法：

    * `override=False`（缺省）：只给承载图**给不出映射**的槽（`ambiguous` 块中部）补对齐；
    * `override=True`：承载图给了映射、但该槽语音与映射到的原版行**不一致**且语音号在
      整脚本内唯一时，**以语音为准改写**该映射（承载图的机械锚可能是假锚，见
      `resource/carrier_quirks.json`）。

    找不到唯一同号行 ⇒ 保留原映射（`override` 时）或不补（否则）。
    返回补齐/校正后的 `{steam 槽: 原版行}`（新 dict，不改入参）。
    """
    by_voice = {}
    for i, r in enumerate(o_own):
        for v in (r.get('voice') or []):
            by_voice.setdefault(v, []).append(i)
    out = dict(s2o)
    for k, r in enumerate(s_own):
        vs = r.get('voice') or []
        if len(vs) != 1:
            continue
        cand = by_voice.get(vs[0]) or []
        if len(cand) != 1:
            continue
        cur = out.get(k)
        if cur is None:
            out[k] = cand[0]
        elif override and cur != cand[0] and vs[0] not in (o_own[cur].get('voice') or []):
            out[k] = cand[0]
    return out


def interp_align(s2o):
    """在两个**已对齐**槽之间补 1:1 缺口：两侧空档长度相等时逐槽内插。

    承载图的 `ambiguous` 块中部给不出映射，但若某个缺口两侧的「未对齐槽数」与
    「原版行数」相等，则该段是 1:1（只是机械锚没钉上）⇒ 逐槽内插。长度不等 ⇒ 不插
    （真缺口，交人工）。
    """
    ks = sorted(s2o)
    out = dict(s2o)
    for a, b in zip(ks, ks[1:]):
        gap_k = b - a - 1
        gap_r = s2o[b] - s2o[a] - 1
        if gap_k > 0 and gap_k == gap_r:
            for i in range(1, gap_k + 1):
                out[a + i] = s2o[a] + i
    return out


def product_sequence(drops, inserts, n_steam):
    """复现写盘器的产物槽序：`[('steam', k) | ('orig', r), ...]`。

    与 `tool/writer.rebuild_host`／`script/verify_sync.expected_sequence` 同口径
    （锚点已由计划器 normalize 到保留槽）。
    """
    by_anchor = {}
    for a, r0, r1 in inserts:
        by_anchor.setdefault(a, []).append((r0, r1))
    seq = []
    for r0, r1 in sorted(by_anchor.get(-1, [])):
        seq.extend(('orig', r) for r in range(r0, r1 + 1))
    drp = set(drops)
    for k in range(n_steam):
        if k not in drp:
            seq.append(('steam', k))
        for r0, r1 in sorted(by_anchor.get(k, [])):
            seq.extend(('orig', r) for r in range(r0, r1 + 1))
    return seq


def restored_scope(s_own, o_own, drops, inserts, n_steam):
    """逐 Steam 保留槽 k：k 设置的显示**是否在「还原演出在屏」的行上仍然在屏**。

    用于把演出同步**限制在还原范围内**：只有「还原内容在屏时也看得见」的 Steam 演出
    才做同步；否则两侧差属 Steam 与原版的版本差（如 AGE_010 前段的 `BG20B_01B/S`、
    立绘姿势差），不属还原范围（改动面收敛，见 doc/restoration-route.md §2）。
    """
    origin_src, setter = {}, {}
    out = {}
    for kind, idx in product_sequence(drops, inserts, n_steam):
        own = (s_own[idx] if kind == 'steam' else o_own[idx]).get('display') or {}
        for chan in own:
            origin_src[chan] = kind
            setter[chan] = idx if kind == 'steam' else None
        if any(v == 'orig' for v in origin_src.values()):
            for chan, src in origin_src.items():
                if src == 'steam' and setter[chan] is not None:
                    out[setter[chan]] = True
    return out
