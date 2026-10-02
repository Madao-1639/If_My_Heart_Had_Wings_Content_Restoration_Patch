"""验收取证：产物回读、NameTable、与旧提取的槽位数差异、复读(相邻同文)检测。

写 tmp/acceptance.md，供报告引用。
"""
import io
import json
import re
import sys
from collections import Counter

sys.path.insert(0, '.')
sys.path.insert(0, 'script')
import build_fan_translations as B  # noqa: E402
from tool import fancn  # noqa: E402
from tool import textfix  # noqa: E402

OUT_DIR = 'resource/fan_cn'
rows = [json.loads(l) for l in open('resource/corpus/pairing.jsonl', encoding='utf-8')]
fixes = {}
for l in open('resource/corpus/review_fixes.jsonl', encoding='utf-8'):
    d = json.loads(l)
    fixes[(d['script'], d['idx'])] = d['cn']
legacy = B.load_legacy_totals('resource/corpus/zh')
manifest = json.load(open(f'{OUT_DIR}/manifest.json', encoding='utf-8'))

by_script = {}
for r in rows:
    by_script.setdefault(r['script'], []).append(r)

out = io.open('tmp/acceptance.md', 'w', encoding='utf-8')

# 1. 产物回读 == 门禁内 CN
mismatch = checked = 0
bad_samples = []
for name, srows in sorted(by_script.items()):
    back = fancn.load_texts(name)
    for r in srows:
        if r['kind'] == 'name':
            continue
        if r['kind'] == 'ctrl':
            want = '%P'
        else:
            want = textfix.emit(r['jp'], r['cn'],
                              fixes.get((r['script'], r['idx'])))
        got = back[r['idx']] if r['idx'] < len(back) else None
        checked += 1
        if got != want:
            mismatch += 1
            if len(bad_samples) < 10:
                bad_samples.append((name, r['idx'], want, got))
out.write('# 验收取证\n\n## 1. 产物回读\n')
out.write(f'- 比对槽位 {checked}，与门禁内中文不一致 {mismatch}\n')
for s, i, w, g in bad_samples:
    out.write(f'  - {s} idx{i}\n      期望 {w}\n      实得 {g}\n')

# 2. NameTable
nt_map = fancn.load_name_table()
lines = [f'{mk}\t{disp}' for mk, disp in nt_map.items()]
KANA = textfix.KANA_ANY
out.write('\n## 2. NameTable（说话人名）\n')
out.write(f'- 条目 {len(lines)}，含假名 {sum(1 for l in lines if KANA.search(l.split(chr(9))[1]))}\n')
out.write(f'- 与日文同形的条目 {manifest["totals"]["nametable_identity"]}：\n')
for l in lines:
    mk, disp = l.split('\t')
    if disp == mk[3:]:
        out.write(f'  - {mk} -> {disp}\n')

# 3. 与旧提取（per-key walker）的槽位数差异
out.write('\n## 3. 每脚本槽位数 vs 旧提取\n')
out.write('| script | 新 size | legacy total | 差 |\n|---|---|---|---|\n')
for name in sorted(manifest['scripts']):
    st = manifest['scripts'][name]
    lg = legacy.get(name)
    if lg is None or lg == st['size']:
        continue
    out.write(f'| {name} | {st["size"]} | {lg} | {st["size"] - lg:+d} |\n')

# 4. 复读检测：同一脚本内相邻槽位中文完全相同、但日文不同
FLOW = re.compile(r'%K|%P|\\n')
dup = []
for name, srows in sorted(by_script.items()):
    seq = [(r['idx'], r['kind'], r['jp'],
            textfix.emit(r['jp'], r['cn'], fixes.get((name, r['idx']))))
           for r in srows if r['kind'] in ('dlg', 'flag', 'menu')]
    for (i1, k1, j1, c1), (i2, k2, j2, c2) in zip(seq, seq[1:]):
        if c1 and c1 == c2 and j1 != j2 and FLOW.sub('', c1).strip():
            dup.append((name, i1, i2, j1, j2, c1))
out.write('\n## 4. 相邻同文（复读候选）\n')
out.write(f'- 命中 {len(dup)} 对\n')
for name, i1, i2, j1, j2, c1 in dup[:60]:
    out.write(f'- {name} idx{i1}/idx{i2}\n    JP1 {j1}\n    JP2 {j2}\n    CN  {c1}\n')

# 5. 全库同文聚集（一个中文串被多条不同日文行共用 = 查表错位的强信号）
share = Counter()
text2jp = {}
for r in rows:
    if r['kind'] not in ('dlg', 'flag', 'menu'):
        continue
    c = textfix.emit(r['jp'], r['cn'], fixes.get((r['script'], r['idx'])))
    core = FLOW.sub('', c).strip()
    if len(core) < 6:
        continue
    share[core] += 1
    text2jp.setdefault(core, []).append((r['script'], r['idx'], r['jp']))
out.write('\n## 5. 跨脚本重复中文（长度>=6，出现次数 top）\n')
for c, n in share.most_common(25):
    if n < 3:
        break
    out.write(f'- {n}x  {c}\n')
    for s, i, jp in text2jp[c][:4]:
        out.write(f'    {s} idx{i} JP {jp}\n')
out.close()

print('readback', checked, 'mismatch', mismatch,
      'adjacent-dup', len(dup), 'shared-text', sum(1 for v in share.values() if v >= 3))
