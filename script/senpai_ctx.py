"""统计规范化后仍含「前辈」的行，按 (说话人, 是否点名) 分组，供称谓裁决。

说话人取自同一脚本内、该对白行之前最近的一条 %LC 名字行（引擎的说话人标记就是
按这个顺序生效的）。只写文件，不打控制台。
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

by_script = collections.OrderedDict()
for line in (ROOT / 'resource' / 'corpus' / 'pairing.jsonl').read_text('utf-8').splitlines():
    r = json.loads(line)
    by_script.setdefault(r['script'], []).append(r)

rows = []
spk_by_form = collections.Counter()
for script, rs in by_script.items():
    speaker = ''
    for r in sorted(rs, key=lambda x: (x['idx'] if x['idx'] is not None else -1)):
        if r['kind'] == 'name':
            if r['cn']:
                speaker = r['cn']
            continue
        if r['kind'] != 'dlg':
            continue
        cn = textfix.emit(r['jp'] or '', r['cn'] or '', fixes.get((script, r['idx'])))
        if '前辈' in cn:
            jp = r['jp'] or ''
            rows.append((script, r['idx'], speaker, jp, cn))
            for name in ('天音', '碧', '小鳥', '小鸟', '揚羽', '扬羽', '亜紗', '亚纱',
                         '依瑠', '佳奈子', '朱莉', 'イスカ', '易鸟', '柾次', '亮子',
                         '早苗', '由佳', '先生'):
                if name in jp:
                    spk_by_form[(name, speaker[3:] if speaker.startswith('%LC') else speaker)] += 1
                    break
        if '学姐' in cn or '学长' in cn:
            jp = r['jp'] or ''
            for name in ('天音', '碧', '小鳥', '小鸟', '揚羽', '扬羽', '亜紗', '亚纱',
                         '依瑠', '佳奈子', '朱莉', 'イスカ', '易鸟'):
                if name in jp:
                    spk_by_form[(name, 'OK:' + (speaker[3:] if speaker.startswith('%LC') else speaker))] += 1
                    break

L = ['# 称谓「前辈」裁决素材', '',
     f'- 规范化后仍含「前辈」的对白 {len(rows)} 行', '',
     '## 按 (日文点名, 说话人) 分布（OK: 前缀 = 该行已译成学姐/学长）', '']
for (name, spk), n in spk_by_form.most_common():
    L.append(f'- {name} <- {spk}: {n}')
L += ['', '## 明细', '']
for script, idx, spk, jp, cn in rows:
    L.append(f'- {script} idx{idx} spk={spk}')
    L.append(f'    JP {jp}')
    L.append(f'    CN {cn}')
(ROOT / 'tmp' / 'senpai_ctx.md').write_text('\n'.join(L) + '\n', encoding='utf-8')
print('rows', len(rows), 'forms', len(spk_by_form))
