# -*- coding: utf-8 -*-
"""按 doc/resource-naming.md 生成号段候选表 resource/rename_map.json。

**改名路线已取消**（`doc/resource-naming.md` §1、§8）：两侧同名的冲突一律**整名覆盖**
⇒ 不进本表、不改名、不改脚本引用；顶包也只改写那一个存活调用点。号段（`9X`／`8X`）
只服务 **Steam 侧不存在的新增成员**，而新增成员按 §1 第 4 条**直接继承原版名**
⇒ 本体还原侧当前**无号段用途**。故本脚本恒出空的 `voice`／`sprite`／`mos`／`est` 表，
只保留**诊断清单**（冲突面与引用面读数、`unused_conflicts`），供人工核对。

口径（历史，仅存于本脚本注释，规则已停用）：
- 仅「两侧同名且内容不同 **且 被还原内容引用**」的资源改名进号段；Steam 缺失的资源直接继承原版名。
- 号段：L1-L3 ⇒ `9X`，**从后往前**分配，分配后不得重排或复用。8X 留给 L4。
- 连带：B/S 双后缀变体与 `.MOS` 随基名一起改名搬运。

被还原内容引用 = 判读台账的插入 span（inserts ∪ rebind 行区间 → 原版指令 span）+
A-1 五个整脚本——**指令操作数级**扫描（0x1e/0x28/0x33/0x34 的第二个字符串），
不漏同行第二引用（行级归属曾漏计，2026-10-02 改口径）。

幂等：同一批输入两次运行产出逐字节一致。
"""
import collections
import glob
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
from tool import arcbuild, v5lib, ws2  # noqa: E402
from tool import paths  # noqa: E402
from tool.ws2conv import load_orig_formats, parse as conv_parse  # noqa: E402

OUT_JSON = os.path.join(ROOT, 'resource', 'rename_map.json')
OUT_MD = os.path.join(ROOT, 'tmp', 'rename_map.md')

# 改名路线已取消（doc/resource-naming.md §1）：同名冲突一律整名覆盖，本表恒空。
# 保留开关而非删除代码，是为「号段编号」这一潜在用途（§8 待裁定）留回退位。
RENAME_ROUTE_RETIRED = True

A1_SCRIPTS = ['ASA_002', 'ASA_004', 'YOR_003', 'YOR_005', 'YOR_007']

VOICE_RX = re.compile(r'^([A-Za-z]+)_(\d{4})\.ogg$', re.I)
SPRITE_RX = re.compile(r'^([A-Za-z]+)_(\d{2})_(\d{2,3})([BS])\.png$', re.I)
SPRITE_RX2 = re.compile(r'^([A-Za-z]+?)(\d{2})_(\d{2})([BS])\.png$', re.I)
EST_RX = re.compile(r'^(EST)_(\d{3,4})\.png$', re.I)

RESOURCE_ARCHIVES = ['VOICE.arc', 'Chip1.arc', 'CHIP2.arc', 'CHIP3.arc', 'CHIP4.arc',
                     'CHIP5.arc', 'CHIP6.arc', 'GRAPHIC.arc', 'SE.arc', 'BGM.arc']
SPRITE_ARCHIVES = ['CHIP2.arc', 'CHIP3.arc', 'CHIP4.arc', 'CHIP5.arc', 'CHIP6.arc', 'Chip1.arc', 'GRAPHIC.arc']

_odec = {}


def rio_dec_orig(script):
    if script not in _odec:
        for nb, d in arcbuild.read_raw(os.path.join(paths.orig_dir(), 'Rio.arc')):
            n = nb.decode('utf-16le', 'replace')
            if n.lower() == script.lower() + '.ws2':
                _odec[script] = ws2.decode(d)
                break
    return _odec[script]


def parse_sprite(name):
    m = SPRITE_RX.match(name)
    if m:
        return (m.group(1), m.group(2), m.group(3), m.group(4), 'std')
    m = SPRITE_RX2.match(name)
    if m:
        return (m.group(1), m.group(2), m.group(3), m.group(4), 'compact')
    return None


def sprite_patch_name(role, scene, diff, letter, shape):
    scene = int(scene)
    if shape == 'compact':
        return '%s%02d_%s%s.png' % (role, scene, diff, letter)
    return '%s_%02d_%s%s.png' % (role, scene, diff, letter)


def load_conflicts():
    with open(os.path.join(ROOT, 'resource', 'res_diff.json'), encoding='utf-8') as f:
        rd = json.load(f)
    out = {}
    for arch in RESOURCE_ARCHIVES:
        e = rd.get(arch)
        if not e:
            continue
        for n in e.get('conflict', []):
            name = n['name'] if isinstance(n, dict) else n
            low = name.lower()
            if VOICE_RX.match(name):
                kind = 'voice'
            elif parse_sprite(name):
                kind = 'sprite'
            elif EST_RX.match(name):
                kind = 'est'
            else:
                kind = 'other'
            out[low] = (arch, name, kind)
    return out


def load_restored_spans(orig_fmts):
    """{script: [(i0,i1) 指令下标 span]}：台账 inserts ∪ rebind 行区间 → 原版指令 span。"""
    spans = collections.defaultdict(list)
    for p in sorted(glob.glob(os.path.join(ROOT, 'resource', 'adjudication', '*.jsonl'))):
        script = os.path.basename(p)[:-6]
        if script.startswith('rereview'):
            continue
        blocks = [json.loads(l) for l in open(p, encoding='utf-8') if l.strip()]
        ranges = []
        for e in blocks:
            for c in e.get('cells', []):
                if c['action'] == 'rebind':
                    ranges.append((c['bind_orig_row'], c['bind_orig_row']))
            for ins in e.get('inserts', []):
                ranges.append((ins['orig_rows'][0], ins['orig_rows'][1]))
        if not ranges:
            continue
        if script.upper() in A1_SCRIPTS:
            spans[script.upper()].append((0, len(conv_parse(rio_dec_orig(script.upper()), orig_fmts)[0])))
            continue
        oinstrs, _t = conv_parse(rio_dec_orig(script), orig_fmts)
        o14 = [j for j, (op, ops) in enumerate(oinstrs) if op == 0x14]
        for r0, r1 in ranges:
            i0 = o14[r0 - 1] + 1 if r0 > 0 else 0
            i1 = o14[r1 + 1] if r1 + 1 < len(o14) else len(oinstrs)
            spans[script].append((i0, i1))
    return spans


def load_referenced(spans, orig_fmts):
    """span 内指令操作数的资源引用：{name_lower: 原名}（指令级，不漏同行第二引用）。"""
    ref = {}
    for script, sps in sorted(spans.items()):
        instrs, _t = conv_parse(rio_dec_orig(script), orig_fmts)
        for i0, i1 in sps:
            for j in range(i0, min(i1, len(instrs))):
                op, ops = instrs[j]
                if op not in (0x1E, 0x28, 0x33, 0x34):
                    continue
                parts = ops.split(b'\x00')
                if len(parts) < 2:
                    continue
                fname = parts[1].decode('ascii', 'replace').upper()
                if fname:
                    ref.setdefault(fname.lower(), fname)
    return ref


def known_names():
    with open(os.path.join(ROOT, 'resource', 'res_diff.json'), encoding='utf-8') as f:
        rd = json.load(f)
    known = set()
    for arch, e in rd.items():
        for key in ('orig_only', 'steam_only', 'conflict'):
            for n in e.get(key, []):
                name = n['name'] if isinstance(n, dict) else n
                known.add(name.lower())
    return known


def orig_has(archive, name_low):
    with open(os.path.join(ROOT, 'resource', 'res_diff.json'), encoding='utf-8') as f:
        rd = json.load(f)
    e = rd.get(archive, {})
    names = {(n['name'] if isinstance(n, dict) else n).lower()
             for key in ('orig_only', 'conflict') for n in e.get(key, [])}
    return name_low in names


def main():
    ofmt = load_orig_formats(paths.orig_dir())
    conflicts = load_conflicts()
    spans = load_restored_spans(ofmt)
    ref = load_referenced(spans, ofmt)
    known = known_names()

    targets, unparseable = [], []
    for low, name in sorted(ref.items()):
        if low not in conflicts:
            continue
        arch, cname, kind = conflicts[low]
        if RENAME_ROUTE_RETIRED:
            continue                      # 同名冲突一律整名覆盖 ⇒ 不进本表
        if kind == 'other':
            unparseable.append({'name': cname, 'archive': arch, 'referenced_as': name,
                                'reason': '命名规则未覆盖'})
            continue
        targets.append({'archive': arch, 'name': cname, 'kind': kind})

    by_kind = collections.defaultdict(list)
    for t in targets:
        by_kind[t['kind']].append(t)

    used = set()
    mapping = []

    def alloc_voice(role):
        for n in range(9999, 8999, -1):
            cand = '%s_%04d.ogg' % (role, n)
            if cand.lower() not in used and cand.lower() not in known:
                return cand
        return None

    _used_scenes = set()

    def alloc_scene():
        n = next((s for s in range(99, 89, -1) if s not in _used_scenes), None)
        if n is not None:
            _used_scenes.add(n)
        return n

    for t in sorted(by_kind['voice'], key=lambda x: x['name'].lower()):
        m = VOICE_RX.match(t['name'])
        cand = alloc_voice(m.group(1))
        if cand is None:
            unparseable.append({'name': t['name'], 'archive': t['archive'], 'reason': '语音 9X 段耗尽'})
            continue
        mapping.append({'kind': 'voice', 'role': 'primary', 'source_archive': t['archive'],
                        'orig': t['name'], 'patch': cand})
        used.add(cand.lower())

    groups = collections.defaultdict(list)
    for t in by_kind['sprite']:
        p = parse_sprite(t['name'])
        groups[(p[0].lower(), p[1], t['archive'])].append((t, p))
    for key in sorted(groups):
        primaries = []
        new_scene = alloc_scene()
        if new_scene is None:
            unparseable.append({'name': ','.join(sorted(t['name'] for t, _ in groups[key])),
                                'reason': '立绘 9X 场景段耗尽'})
            continue
        for t, p in sorted(groups[key], key=lambda x: x[0]['name'].lower()):
            role, _scene, diff, letter, shape = p
            patch = sprite_patch_name(role, new_scene, diff, letter, shape)
            mapping.append({'kind': 'sprite', 'role': 'primary', 'source_archive': t['archive'],
                            'orig': t['name'], 'patch': patch})
            used.add(patch.lower())
            primaries.append((p, patch))
        prim_orig = {e['orig'].lower() for e in mapping if e['role'] == 'primary'}
        for p, patch in primaries:
            role, scene, diff, letter, shape = p
            sib_letter = 'B' if letter.upper() == 'S' else 'S'
            sib = sprite_patch_name(role, scene, diff, sib_letter, shape)
            sib_low = sib.lower()
            if sib_low not in prim_orig:
                src = next((a for a in SPRITE_ARCHIVES if orig_has(a, sib_low)), None)
                if src:
                    patch_sib = sprite_patch_name(role, new_scene, diff, sib_letter, shape)
                    if patch_sib.lower() not in used:
                        mapping.append({'kind': 'sprite', 'role': 'sibling', 'source_archive': src,
                                        'orig': sib, 'patch': patch_sib})
                        used.add(patch_sib.lower())
            for orig_png, new_png in ((sprite_patch_name(role, scene, diff, letter, shape), patch),
                                      (sprite_patch_name(role, scene, diff, sib_letter, shape),
                                       sprite_patch_name(role, new_scene, diff, sib_letter, shape))):
                mos_low = os.path.splitext(orig_png)[0].lower() + '.mos'
                src = next((a for a in SPRITE_ARCHIVES if orig_has(a, mos_low)), None)
                if src:
                    patch_mos = os.path.splitext(new_png)[0] + '.mos'
                    if patch_mos.lower() not in used:
                        mapping.append({'kind': 'mos', 'role': 'mos', 'source_archive': src,
                                        'orig': mos_low, 'patch': patch_mos})
                        used.add(patch_mos.lower())

    for t in sorted(by_kind['est'], key=lambda x: x['name'].lower()):
        cand = None
        for n in range(999, 899, -1):
            c = 'EST_%d.png' % n
            if len(c.rsplit('.', 1)[0]) <= 7 and c.lower() not in used and c.lower() not in known:
                cand = c
                break
        if cand is None:
            unparseable.append({'name': t['name'], 'archive': t['archive'], 'reason': 'EST 9X 段耗尽'})
            continue
        mapping.append({'kind': 'est', 'role': 'primary', 'source_archive': t['archive'],
                        'orig': t['name'], 'patch': cand})
        used.add(cand.lower())

    errs = []
    patches = [e['patch'].lower() for e in mapping]
    if len(patches) != len(set(patches)):
        errs.append('G2 patch 名重复')
    for e in mapping:
        if e['kind'] == 'est' and len(e['patch'].rsplit('.', 1)[0]) > 7:
            errs.append('G2 EST stem 超限: %s' % e['patch'])
    prim_orig_low = {e['orig'].lower() for e in mapping if e['role'] == 'primary'}
    if not RENAME_ROUTE_RETIRED:
        for low, name in sorted(ref.items()):
            if low in conflicts and conflicts[low][2] in ('voice', 'sprite', 'est') and low not in prim_orig_low:
                errs.append('G1 引用冲突未映射: %s' % name)
    unused = sorted((conflicts[low][1], conflicts[low][0])
                    for low in conflicts
                    if conflicts[low][2] in ('voice', 'sprite', 'est') and low not in ref)

    result = {
        'meta': {
            'spec': 'doc/resource-naming.md',
            'segment': '9X (L1-L3)；8X 留给 L4（当前均无用途）',
            'rule': ('改名路线已取消：同名冲突一律整名覆盖、不进本表；Steam 缺失的资源直接继承原名；'
                     '号段只服务新增成员（当前无需求）'),
            'retired': bool(RENAME_ROUTE_RETIRED),
            'reference_scan': '指令操作数级（0x1e/0x28/0x33/0x34 第二字符串），span = 台账插入区间',
            'restored_scripts': sorted(spans),
            'referenced_names': len(ref),
            'conflict_names': len(conflicts),
        },
        'voice': [{k: e[k] for k in ('source_archive', 'orig', 'patch')} for e in mapping if e['kind'] == 'voice'],
        'sprite': [{k: e[k] for k in ('source_archive', 'orig', 'patch', 'role')} for e in mapping if e['kind'] == 'sprite'],
        'mos': [{k: e[k] for k in ('source_archive', 'orig', 'patch')} for e in mapping if e['kind'] == 'mos'],
        'est': [{k: e[k] for k in ('source_archive', 'orig', 'patch')} for e in mapping if e['kind'] == 'est'],
        'unused_conflicts': [{'archive': a, 'name': n} for n, a in unused],
        'unparseable': unparseable,
    }
    with open(OUT_JSON, 'w', encoding='utf-8', newline='\n') as f:
        json.dump(result, f, ensure_ascii=False, indent=1, sort_keys=True)
        f.write('\n')

    md = ['# rename_map 报表（doc/resource-naming.md）', '',
          '- 改名路线：%s' % ('已取消（同名冲突一律整名覆盖 ⇒ 本表恒空）'
                              if RENAME_ROUTE_RETIRED else '启用'),
          '- 改名 %d 项：语音 %d、立绘 %d（primary+sibling）、.MOS %d、事件 CG %d'
          % (len(mapping), len(result['voice']), len(result['sprite']), len(result['mos']), len(result['est'])),
          '- 冲突面（诊断，不作处置依据）：%d 名；其中未被还原内容引用 %d 名' % (len(conflicts), len(unused)),
          '- 规则解不掉：%d' % len(unparseable), '']
    for title, key in (('语音（千位 9X，9999 往下）', 'voice'), ('立绘（场景段 9X，99 往下）', 'sprite'),
                       ('事件 CG（EST_9xx，999 往下）', 'est')):
        md += ['## %s' % title, '', '| 原名 | 补丁名 | 来源归档 | 角色 |', '|---|---|---|---|']
        for e in result[key]:
            md.append('| %s | %s | %s | %s |' % (e['orig'], e['patch'], e['source_archive'], e.get('role', 'primary')))
        md.append('')
    if unparseable:
        md += ['## 规则解不掉（须人工裁定）', '', '```json', json.dumps(unparseable, ensure_ascii=False, indent=1), '```', '']
    with open(OUT_MD, 'w', encoding='utf-8', newline='\n') as f:
        f.write('\n'.join(md))

    print('rename_map: voice %d / sprite %d / mos %d / est %d ; unused %d ; unparseable %d'
          % (len(result['voice']), len(result['sprite']), len(result['mos']),
             len(result['est']), len(unused), len(unparseable)))
    for m in errs:
        print('GATE-FAIL ' + m)
    sys.exit(1 if errs or unparseable else 0)


if __name__ == '__main__':
    main()
