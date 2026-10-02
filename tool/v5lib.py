"""V-5/V-6 判读共享库：行文本、官方 zh、语音/图片锚点、非平凡块、资源存在性判据。

行索引口径与承载图（resource/carrier_map.json）一致：dlg/ctrl 行、0 起；
块区间沿用承载图的**闭区间** [start, end]。
资源存在性判据用 tmp/scope/res_diff.json 的名单，避免全量哈希比对：
名字不在某归档 `orig_only` 名单 ⇒ Steam 侧存在；不在 `steam_only` 名单 ⇒ 原版侧存在。
"""
import bisect
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, 'tmp', 'restdiff'))
from tool import arcbuild, ws2, scriptext  # noqa: E402
import paths  # noqa: E402

VOICE_RX = re.compile(rb'char[A-Z]{2,4}\x00([A-Za-z0-9_]+\.OGG)\x00', re.I)
PNG_RX = re.compile(rb'\x33[A-Za-z0-9_]{2,12}\x00([A-Za-z0-9_.\-]+\.PNG)\x00', re.I)

_carrier = None
_resdiff = None
_lng = None
_rio_cache = {}


def carrier():
    global _carrier
    if _carrier is None:
        with open(os.path.join(ROOT, 'resource', 'carrier_map.json'), encoding='utf-8') as f:
            _carrier = json.load(f)
    return _carrier


def _resdiff_sets(archive):
    """(orig_only_upper, steam_only_upper) 名单集合。"""
    global _resdiff
    if _resdiff is None:
        with open(os.path.join(ROOT, 'tmp', 'scope', 'res_diff.json'), encoding='utf-8') as f:
            raw = json.load(f)
        _resdiff = {a: ({n.upper() for n in e.get('orig_only', [])},
                        {n.upper() for n in e.get('steam_only', [])})
                    for a, e in raw.items()}
    return _resdiff[archive]


def voice_in_steam(name):
    oo, _ = _resdiff_sets('VOICE.arc')
    return name.upper() not in oo


def voice_in_orig(name):
    _, so = _resdiff_sets('VOICE.arc')
    return name.upper() not in so


def se_in_steam(name):
    oo, _ = _resdiff_sets('SE.arc')
    return name.upper() not in oo


def png_in_steam(name):
    """在全部归档的 orig_only 名单里都找不到 ⇒ Steam 某归档存在。"""
    u = name.upper()
    _resdiff_sets('VOICE.arc')  # 触发加载
    for oo, _ in _resdiff.values():
        if u in oo:
            return False
    return True


def lng_official():
    global _lng
    if _lng is None:
        with open(os.path.join(ROOT, 'tmp', 'align', 'steam_lng_text.json'), encoding='utf-8') as f:
            _lng = json.load(f)
    return _lng


def zh_official(script):
    """官方 zh-CN 按槽位序的文本列表（U-9：CO1_003/CO2_002 无数据；U-10：条数可能比槽位多）。"""
    return lng_official().get(script)


def rio(side):
    """{脚本名大写: ws2 原始字节}，side='steam'|'orig'。"""
    if side not in _rio_cache:
        base = paths.STEAM if side == 'steam' else paths.orig_dir()
        out = {}
        for nb, d in arcbuild.read_raw(os.path.join(base, 'Rio.arc')):
            try:
                n = nb.decode('utf-16le')
            except UnicodeDecodeError:
                continue
            if n.lower().endswith('.ws2'):
                out[n[:-4].upper()] = d
        _rio_cache[side] = out
    return _rio_cache[side]


def rows(side, script):
    """dlg/ctrl 行（与承载图同口径）：[{'idx','kind','off','jp',...}]，jp 即该侧文本。"""
    raw = rio(side).get(script.upper())
    if raw is None:
        return []
    return [r for r in scriptext.script_rows(script, raw) if r['kind'] in ('dlg', 'ctrl')]


def row_tokens(side, script):
    """每行 (voice, png)：token 归属其后最近一行，无则向前一行借。"""
    raw = rio(side).get(script.upper())
    if raw is None:
        return []
    dec = ws2.decode(raw)
    rl = rows(side, script)
    toks = []
    for rx in (VOICE_RX, PNG_RX):
        for m in rx.finditer(dec):
            toks.append((m.start(), m.group(1).decode('ascii', 'replace').upper()))
    toks.sort()
    offs = [r['off'] for r in rl]
    vp = [[None, None] for _ in rl]
    for x, v in toks:
        k = bisect.bisect_right(offs, x)
        if k >= len(rl):
            continue
        if v.endswith('.OGG') and vp[k][0] is None:
            vp[k][0] = v
        elif v.endswith('.PNG') and vp[k][1] is None:
            vp[k][1] = v
    pv = pp = None
    for i in range(len(rl)):
        if vp[i][0] is None:
            vp[i][0] = pv
        if vp[i][1] is None:
            vp[i][1] = pp
        pv, pp = vp[i]
    return [tuple(x) for x in vp]


def jp_texts(script):
    """resource/corpus/jp 的原版行文本列表；文件不存在或长度与承载图行数不一致时返回 None。"""
    p = os.path.join(ROOT, 'resource', 'corpus', 'jp', script + '.json')
    if not os.path.exists(p):
        return None
    with open(p, encoding='utf-8') as f:
        d = json.load(f)
    texts = d['texts']
    rl = rows('orig', script)
    if len(texts) != len(rl):
        return None
    return texts


def blocks(script):
    """非平凡块（ambiguous / orig_only / steam_only），承载图原序。"""
    return [b for b in carrier()[script.upper()]['blocks']
            if b['kind'] in ('ambiguous', 'orig_only', 'steam_only')]


def scripts_with_blocks():
    """有非平凡块的脚本名列表（carrier 键序）。"""
    return [s for s, e in carrier().items() if blocks(s)]
