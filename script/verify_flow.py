"""校验两点，为验收报告取证：

1. 对齐前 JP/CN 的 %K/%P 序列差异有多少行、align_terminator 是否真的把它们改平；
2. 产物 JSON 回读后与门禁内的 CN 是否逐槽一致（G3 的独立复核）。
"""
import io
import json
import re
import sys

sys.path.insert(0, '.')
sys.path.insert(0, 'script')
from tool import textfix  # noqa: E402
from tool import fancn  # noqa: E402

FLOW = re.compile(r'%K|%P')
rows = [json.loads(l) for l in open('resource/corpus/pairing.jsonl', encoding='utf-8')]
fixes = {}
for l in open('resource/corpus/review_fixes.jsonl', encoding='utf-8'):
    d = json.loads(l)
    fixes[(d['script'], d['idx'])] = d['cn']

out = io.open('tmp/verify_flow.md', 'w', encoding='utf-8')
diff_before = diff_after = 0
samples = []
for r in rows:
    if r['kind'] not in ('dlg', 'menu', 'flag'):
        continue
    jp = r['jp']
    cn = textfix.normalize(fixes.get((r['script'], r['idx']), None) or r['cn'] or '')
    if FLOW.findall(jp) != FLOW.findall(cn):
        diff_before += 1
        aligned = textfix.align_terminator(jp, cn)
        if FLOW.findall(jp) != FLOW.findall(aligned):
            diff_after += 1
            if len(samples) < 12:
                samples.append((r['script'], r['idx'], jp, cn, aligned))
out.write(f'- 对齐前 %K/%P 序列不同的行：{diff_before}\n')
out.write(f'- align_terminator 之后仍不同的行：{diff_after}\n\n')
for s, i, jp, cn, al in samples:
    out.write(f'- {s} idx{i}\n    JP {jp}\n    CN {cn}\n    AL {al}\n')

# G3 独立复核：回读产物，逐槽与"门禁内 CN"比对
by_script = {}
for r in rows:
    by_script.setdefault(r['script'], []).append(r)
mismatch = 0
checked = 0
for name, srows in sorted(by_script.items()):
    back = fancn.load_texts(name)
    for r in srows:
        if r['kind'] in ('name', 'ctrl'):
            continue
        cn = textfix.emit(r['jp'], r['cn'], fixes.get((r['script'], r['idx'])))
        got = back[r['idx']] if r['idx'] < len(back) else None
        checked += 1
        if got != cn:
            mismatch += 1
            if mismatch <= 8:
                out.write(f'\n[回读不符] {name} idx{r["idx"]}\n    期望 {cn}\n')
                out.write(f'    实得 {got}\n')
out.write(f'\n- 回读比对槽位 {checked}，不符 {mismatch}\n')
out.close()
print('flow_before', diff_before, 'flow_after', diff_after,
      'readback_checked', checked, 'mismatch', mismatch)
