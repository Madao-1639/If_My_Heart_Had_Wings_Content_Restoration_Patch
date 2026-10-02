"""检测"中文侧没有任何汉字"的行，并按日文是否有实词分成两档。

动机：机械层会删掉孤立假名（`ORPHAN_MORA/ORPHAN_KANA`），删完之后
「ズビシッ！」会变成「！」——非空、无假名，G1/G2 都拦不住，看起来却像漏翻。
本脚本只读产物，不改数据。

档 A（必须处理）：日文侧有实词，中文侧剥掉标点后什么都不剩（拟声/实词被剥空）。
档 B（人工确认）：中文侧无汉字，但仍有内容（多为「ッ！」→「！」这类气音、
    或 Windy/OK 等拉丁专名，通常可接受）。
"""
import io
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from tool import textfix  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent

LEXICAL = re.compile(r'[぀-ヿ㐀-䶿一-鿿]')
HAN = re.compile(r'[㐀-䶿一-鿿]')
FLOW = re.compile(r'%K|%P')
# 标点/空白/引号/括号/记谱符号：剥掉这些之后还剩字符才算"有内容"
# 注意字符类里的连字符必须放在末尾或转义，否则会形成非法区间
PUNCT = re.compile(
    '[\\s"\'#%&()*+,./:;<=>?@^_`|~!?'
    '\\-‐‑‒―–—―…‥・'
    '、。〈〉《》「」『』【】〔〕（）'
    '“”‘’＂＇％＋−−〜〜♪'
    '！＂＃＄％＆＇（）＊＋，−．／：；＜＝＞？＠［＼］＾＿｀｛｜｝～'
    '\\\\]')

fixes = {}
for l in (ROOT / 'resource' / 'corpus' / 'review_fixes.jsonl').read_text('utf-8').splitlines():
    d = json.loads(l)
    fixes[(d['script'], d['idx'])] = d['cn']

a, b = [], []
for l in (ROOT / 'resource' / 'corpus' / 'pairing.jsonl').read_text('utf-8').splitlines():
    r = json.loads(l)
    if r['kind'] == 'name':
        continue
    jp = r['jp'] or ''
    if not LEXICAL.search(jp):
        continue
    cn = textfix.emit(jp, r.get('cn') or '', fixes.get((r['script'], r['idx'])))
    if HAN.search(cn):
        continue
    jp_lex = ''.join(LEXICAL.findall(FLOW.sub('', jp)))
    jp_core = PUNCT.sub('', FLOW.sub('', jp))
    cn_core = PUNCT.sub('', FLOW.sub('', cn))
    rec = {'script': r['script'], 'idx': r['idx'], 'jp': jp, 'cn': cn}
    # 三个以上假名/汉字才算是"有实词"，单个促音/拨音只是气音
    if len(jp_lex) >= 3 and not cn_core:
        a.append(rec)
    else:
        b.append(rec)

L = ['# 中文侧无汉字的行', '',
     f'- 档 A（日文有实词、中文被剥空，必须改写）：{len(a)}',
     f'- 档 B（中文仍有内容，人工确认即可）：{len(b)}', '',
     '## 档 A']
for r in a:
    L.append(f"- {r['script']} idx{r['idx']}")
    L.append(f"    JP {r['jp']}")
    L.append(f"    CN {r['cn']}")
L.append('')
L.append('## 档 B')
for r in b:
    L.append(f"- {r['script']} idx{r['idx']}  JP {r['jp']}  CN {r['cn']}")
(ROOT / 'tmp' / 'nohan_scan.md').write_text('\n'.join(L) + '\n', 'utf-8')

print('A', len(a), 'B', len(b))
