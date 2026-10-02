"""合并并发评审 subagent 的修正提案 → resource/corpus/review_fixes.jsonl（语境层，可追溯）。

提案与人工裁决源层（`resource/corpus/review/`）已不再保留，只保留合并产物本身；
因此本脚本只在源层存在时可运行，缺源层直接拒写，避免从零重建把整表洗空。

校验每条提案：槽位存在、kind 可写、非空、不含假名、不等于日文原句。
同一槽位被多个批次改动时记为冲突，保留 fix_missing（专职漏译）之外的多数写法，
冲突明细写 tmp/fix_conflicts.md 供人工裁决。
"""
import collections
import glob
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# 语境层唯一的事实来源是 resource/corpus/review_fixes.jsonl；本脚本按源层从零重建它，
# 源层（提案 + 人工裁决）已不再保留，此时重建等于把整表洗空，所以直接拒绝执行。
LAYERS = ROOT / 'resource' / 'corpus' / 'review'
if not (glob.glob(str(LAYERS / 'fix_*.jsonl')) + glob.glob(str(LAYERS / 'pin_*.jsonl'))):
    sys.exit('resource/corpus/review has no fix_*/pin_* source layers; refusing to '
             'rebuild (a rebuild from scratch would wipe '
             'resource/corpus/review_fixes.jsonl). Merge new proposals into '
             'resource/corpus/review_fixes.jsonl instead.')

KANA_RE = re.compile(r'[぀-ヿｦ-ﾟ]')
HAN_RE = re.compile(r'[㐀-䶿一-鿿]')
# 长音符 ー 与中黑点 ・ 落在假名区间内，但机械层 textfix.PUNCT_MAP 会把它们换成 — 和 ·，
# 所以提案/pin 里出现这两个字符不算"未译假名"。
PUNCT_KANA_RE = re.compile(r'[ー・]')


def has_kana(cn):
    return bool(KANA_RE.search(PUNCT_KANA_RE.sub('', cn)))

rows = {}
for l in (ROOT / 'resource' / 'corpus' / 'pairing.jsonl').read_text('utf-8').splitlines():
    r = json.loads(l)
    if r['kind'] != 'name':
        rows[(r['script'], r['idx'])] = r

props = collections.defaultdict(list)
files = sorted(glob.glob(str(ROOT / 'resource' / 'corpus' / 'review' / 'fix_*.jsonl')))
for p in files:
    src = Path(p).stem
    for line in Path(p).read_text('utf-8').splitlines():
        line = line.strip()
        if not line:
            continue
        e = json.loads(line)
        props[(e['script'], e['idx'])].append((src, e))

# 人工裁决层：pin_*.jsonl 无条件覆盖多数写法（裁决冲突、补漏译），校验照旧
pins = {}
for p in sorted(glob.glob(str(ROOT / 'resource' / 'corpus' / 'review' / 'pin_*.jsonl'))):
    src = Path(p).stem
    for line in Path(p).read_text('utf-8').splitlines():
        line = line.strip()
        if not line:
            continue
        e = json.loads(line)
        pins[(e['script'], e['idx'])] = (src, e)

bad, conflicts, accepted = [], [], {}
for key, lst in sorted(props.items()):
    r = rows.get(key)
    if r is None:
        bad.append((key, [s for s, _ in lst], 'slot-not-in-pairing'))
        continue
    vals = {}
    for src, e in lst:
        cn = e['cn']
        probs = []
        if not cn.strip():
            probs.append('empty')
        if has_kana(cn):
            probs.append('kana')
        if '\\' in cn.replace('\\n', ''):
            probs.append('stray-backslash')
        if cn.strip() == r['jp'].strip() and HAN_RE.search(r['jp']) and KANA_RE.search(r['jp']):
            probs.append('jp-copy')
        if probs:
            bad.append((key, src, ','.join(probs)))
            continue
        vals.setdefault(cn, []).append(src)
    if not vals:
        continue
    if len(vals) > 1:
        conflicts.append((key, r['jp'], {c: s for c, s in vals.items()}))
    best = max(vals, key=lambda c: (len(vals[c]), c))
    accepted[key] = {'cn': best, 'from': vals[best], 'kind': r['kind']}

pinned = set()
for key, (src, e) in sorted(pins.items()):
    r = rows.get(key)
    if r is None:
        bad.append((key, src, 'pin-slot-not-in-pairing'))
        continue
    cn = e['cn']
    probs = []
    if not cn.strip():
        probs.append('empty')
    if has_kana(cn):
        probs.append('kana')
    if '\\' in cn.replace('\\n', ''):
        probs.append('stray-backslash')
    if cn.strip() == r['jp'].strip() and HAN_RE.search(r['jp']) and KANA_RE.search(r['jp']):
        probs.append('jp-copy')
    if probs:
        bad.append((key, src, 'pin:' + ','.join(probs)))
        continue
    accepted[key] = {'cn': cn, 'from': [src], 'kind': r['kind']}
    pinned.add(key)

with (ROOT / 'resource' / 'corpus' / 'review_fixes.jsonl').open('w', encoding='utf-8') as f:
    for (script, idx), v in sorted(accepted.items()):
        f.write(json.dumps({'script': script, 'idx': idx, 'cn': v['cn'],
                            'from': v['from'], 'kind': v['kind']},
                           ensure_ascii=False) + '\n')

L = ['# 评审提案合并结果', '',
     f'- 提案槽位 {len(props)}，接受 {len(accepted)}，异常 {len(bad)}，冲突 {len(conflicts)}', '',
     '## 异常明细']
for key, src, why in bad:
    jp = rows.get(key, {}).get('jp', '')
    L.append(f'- {key[0]} idx{key[1]} [{src}] {why}')
    L.append(f'    JP {jp}')
L.append('')
L.append(f'## 同槽位多写法（冲突，需人工裁决）/ 已 pin {len(pinned)} 槽')
for key, jp, variants in conflicts:
    mark = '  [已 pin 裁决]' if key in pinned else ''
    L.append(f'- {key[0]} idx{key[1]}{mark}')
    L.append(f'    JP {jp}')
    for cn, src in variants.items():
        L.append(f'    {src} -> {cn}')
(ROOT / 'tmp' / 'fix_conflicts.md').write_text('\n'.join(L) + '\n', 'utf-8')

print('slots', len(props), 'accepted', len(accepted), 'bad', len(bad), 'conflicts', len(conflicts))
