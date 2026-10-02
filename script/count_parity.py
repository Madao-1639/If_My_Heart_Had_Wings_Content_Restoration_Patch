"""条目数对账：日文侧逐 kind 行数 vs 中文产物槽位数，逐脚本严格相等断言。

产物槽位只覆盖有 idx 的行（name 行进 NameTable、空洞槽不产内容），因此对账口径是
"日文侧有内容行数 == 中文侧非空槽位数"。结果写 tmp/count_parity.md
"""
import collections
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from tool import fancn  # noqa: E402

by_kind = collections.Counter()
jp_slots = collections.defaultdict(set)
jp_rows = collections.defaultdict(int)
for line in (ROOT / 'resource' / 'corpus' / 'pairing.jsonl').read_text('utf-8').splitlines():
    r = json.loads(line)
    by_kind[r['kind']] += 1
    if r['kind'] in ('dlg', 'ctrl', 'menu', 'flag'):
        jp_rows[r['script']] += 1
        if r['idx'] is not None:
            jp_slots[r['script']].add(r['idx'])

cn_nonempty = collections.defaultdict(set)
cn_slots = collections.defaultdict(int)
for name in fancn.script_names():
    texts = fancn.load_texts(name)
    cn_slots[name] = len(texts)
    cn_nonempty[name] = {i for i, t in enumerate(texts) if t}

missing = {s: sorted(jp_slots[s] - cn_nonempty[s]) for s in jp_slots
           if jp_slots[s] - cn_nonempty[s]}
unexpected = {s: sorted(cn_nonempty[s] - jp_slots.get(s, set())) for s in cn_nonempty
              if cn_nonempty[s] - jp_slots.get(s, set())}
dup_idx = sum(len(v) for v in jp_slots.values())
n_rows = sum(jp_rows.values())

L = ['# 中日条目数对账', '',
     '## 日文侧按 kind 计数',
     *[f'- {k}: {v}' for k, v in by_kind.most_common()], '',
     f'- 占槽位的行（dlg+ctrl+menu+flag）：{n_rows}',
     f'- 这些行落在的唯一槽位：{dup_idx}（差 {n_rows - dup_idx} = 标签与对白撞同一 idx）',
     f'- 中文产物非空槽位：{sum(len(v) for v in cn_nonempty.values())}',
     f'- 中文产物总槽位（含空洞）：{sum(cn_slots.values())}', '',
     f'## 日文有行、中文无内容（不可接受）：{sum(len(v) for v in missing.values())}', '']
for s, v in sorted(missing.items()):
    L.append(f'- {s}: {v}')
L += ['', f'## 中文有内容、日文无对应行（不可接受）：{sum(len(v) for v in unexpected.values())}', '']
for s, v in sorted(unexpected.items()):
    L.append(f'- {s}: {v}')
(ROOT / 'tmp' / 'count_parity.md').write_text('\n'.join(L) + '\n', 'utf-8')
print('jp_rows', n_rows, 'jp_slots', dup_idx, 'cn_nonempty',
      sum(len(v) for v in cn_nonempty.values()),
      'missing', sum(len(v) for v in missing.values()),
      'unexpected', sum(len(v) for v in unexpected.values()))
