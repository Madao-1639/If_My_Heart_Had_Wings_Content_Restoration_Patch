"""小鳥ちゃん/あげはちゃん 等带昵称后缀的写法，其中文译法是否与说话人绑定。

若「小鸟酱」集中在某个说话人（她对谁都加酱），则保留；否则应按语料多数形式写作「小鸟」。
结果写 tmp/nickname_speaker.md
"""
import collections
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from tool import textfix  # noqa: E402

fixes = {}
for line in (ROOT / 'resource' / 'corpus' / 'review_fixes.jsonl').read_text('utf-8').splitlines():
    e = json.loads(line)
    fixes[(e['script'], e['idx'])] = e['cn']

by_script = collections.defaultdict(list)
for line in (ROOT / 'resource' / 'corpus' / 'pairing.jsonl').read_text('utf-8').splitlines():
    r = json.loads(line)
    by_script[r['script']].append(r)

TARGETS = {'小鳥ちゃん': ('小鸟酱', '小鸟'), 'あげはちゃん': ('扬羽酱', '扬羽'),
           '亜紗ちゃん': ('亚纱酱', '亚纱'), '依瑠ちゃん': ('依瑠酱', '依瑠')}
stat = collections.defaultdict(collections.Counter)
samples = collections.defaultdict(list)

for script, rs in by_script.items():
    rs = sorted(rs, key=lambda x: -1 if x['idx'] is None else x['idx'])
    spk = ''
    for r in rs:
        if r['kind'] == 'name':
            if r['cn']:
                spk = r['cn'].replace('%LC', '').strip()
            continue
        if r['kind'] != 'dlg':
            continue
        jp = r['jp'] or ''
        cn = textfix.normalize(fixes.get((script, r['idx']), r['cn']) or '')
        for tgt, (with_suffix, bare) in TARGETS.items():
            if tgt not in jp:
                continue
            form = with_suffix if with_suffix in cn else (bare if bare in cn else '其他')
            stat[tgt][form] += 1
            samples[(tgt, form, spk)].append((script, r['idx'], cn[:60]))

L = ['# 昵称后缀译法与说话人', '']
for tgt in TARGETS:
    L.append(f'## {tgt}')
    for form, n in stat[tgt].most_common():
        spks = collections.Counter()
        for (t, f, s), rows in samples.items():
            if t == tgt and f == form:
                spks[s or '（旁白）'] += len(rows)
        L.append(f'- {form}: {n}   说话人分布 {ascii(dict(spks.most_common(8)))}')
    L.append('')
(ROOT / 'tmp' / 'nickname_speaker.md').write_text('\n'.join(L) + '\n', 'utf-8')
print(ascii({k: dict(v) for k, v in stat.items()}))
