"""提取准确率对照：产物每一槽的中文与"纯提取原值"差在哪一层。

分类口径（逐槽，只看占位行 dlg/menu/flag/ctrl）：
  same       产物 == 纯提取原值，一字未动
  mech       只有机械归一（繁简/字形/标点/ terminator 对齐）动过
  context    语境层（resource/corpus/review_fixes.jsonl）改写或补译过
  newtext    纯提取侧没有汉字（漏译或被剥空），产物有中文 —— 属就地新译
  other      以上都不符合，需要人工查（数量应为 0）

同时全量列出小类别并附同脚本 ±2 行上下文，供语义复检。
结果写 tmp/extraction_accuracy.md（不打印中日文明文到控制台）。
"""
import collections
import io
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'script'))

from tool import fancn, textfix  # noqa: E402

HAN = re.compile(r'[一-鿿]')
PAIR = ROOT / 'resource' / 'corpus' / 'pairing.jsonl'
FIXES = ROOT / 'resource' / 'corpus' / 'review_fixes.jsonl'
OUT = ROOT / 'tmp' / 'extraction_accuracy.md'
REPORT_FROM = {'pin_kana', 'pin_defects', 'fix_missing', 'pin_variants'}


def load_rows():
    return [json.loads(l) for l in PAIR.read_text('utf-8').splitlines()]


def load_fixes():
    fixes = {}
    for l in FIXES.read_text('utf-8').splitlines():
        d = json.loads(l)
        marks = d['from']
        flat = marks if isinstance(marks, list) else [marks]
        fixes.setdefault((d['script'], d['idx']), []).extend(flat)
    return fixes


def classify(raw, jp, final, in_context):
    """返回该槽的改动层。"""
    if final == raw:
        return 'same'
    mech = textfix.emit(jp, raw)
    if final == mech:
        return 'context' if in_context else 'mech'
    return 'context' if in_context else 'other'


CTRL = re.compile(r'%[A-Za-z0-9]+')
PUNCT = re.compile(r'[\s「」『』〈〉《》（）()［］\[\]【】。．、，,。．：:；;！!？?\.\-—―~～＋+＊*ー〜〃′″’‘“”"\'‘＼\\|/／]+')


def residue(raw):
    """提取侧残留类型，用于给就地新译分组。"""
    if '●' in raw:
        return '地址占位符'
    core = PUNCT.sub('', CTRL.sub('', raw))
    if not core:
        return '只剩标点（漏译）'
    if re.search(r'[぀-ヿ]', core):
        return '日文假名残留'
    if re.search(r'[A-Za-z]', core):
        return '拉丁残留'
    return '只剩标点（漏译）'


def main():
    rows = load_rows()
    fixes = load_fixes()
    by_script = collections.defaultdict(list)
    for r in rows:
        by_script[r['script']].append(r)
    product = {name: fancn.load_map(name) for name in fancn.script_names()}
    slots = {}
    for name, srows in by_script.items():
        got = product.get(name, {})
        slots[name] = sorted((r['idx'], r['jp'], got.get(r['idx'], ''), r['src'])
                             for r in srows if r['idx'] is not None and r['kind'] != 'name')

    def ctx(name, idx, span=2):
        lst = slots[name]
        pos = next((k for k, (i, *_r) in enumerate(lst) if i == idx), None)
        lines = []
        if pos is None:
            return lines
        for k in range(max(0, pos - span), min(len(lst), pos + span + 1)):
            i, jp, fin, src = lst[k]
            tag = '>>' if i == idx else '  '
            lines.append(f'{tag} idx{i} [{src}] JP {jp}')
            lines.append(f'        CN {fin}')
        return lines

    stat = collections.Counter()
    src_stat = collections.defaultdict(collections.Counter)
    newtext, others, contexts = [], [], collections.Counter()
    full_lists = collections.defaultdict(list)

    for name, srows in sorted(by_script.items()):
        got = product.get(name, {})
        for r in srows:
            if r['kind'] == 'name' or r['idx'] is None:
                continue
            final = got.get(r['idx'])
            if final is None:
                stat['other'] += 1
                others.append((name, r['idx'], r['cn'], final))
                continue
            raw = r['cn']
            marks = fixes.get((name, r['idx']), [])
            cat = classify(raw, r['jp'], final, bool(marks))
            stat[cat] += 1
            src_stat[r['src']][cat] += 1
            if not HAN.search(raw or '') and HAN.search(final):
                newtext.append((residue(raw or ''), name, r['idx'], r['src'],
                                r['jp'], raw, final, marks))
            for m in marks:
                contexts[m] += 1
                if m in REPORT_FROM:
                    full_lists[m].append((name, r['idx'], r['src'], r['jp'], raw, final))
            if r['src'] in ('need-translate', 'crc-tail'):
                full_lists[r['src']].append(
                    (name, r['idx'], r['src'], r['jp'], raw, final))

    out = io.open(OUT, 'w', encoding='utf-8')
    total = sum(stat.values())
    out.write('# 提取准确率对照\n\n')
    out.write(f'- 产物槽位（占位行）：{total}\n')
    for k in ('same', 'mech', 'context', 'newtext', 'other'):
        out.write(f'- {k}: {stat[k]}（{stat[k] / total * 100:.2f}%）\n')
    out.write('\n## 按提取来源 × 改动层\n')
    for src, c in sorted(src_stat.items()):
        out.write(f'- {src}: ' + ', '.join(f'{k} {v}' for k, v in sorted(c.items())) + '\n')
    out.write('\n## 语境层各来源落地的槽位数\n')
    for k, v in contexts.most_common():
        out.write(f'- {k}: {v}\n')

    out.write(f'\n## 就地新译（提取侧无汉字、产物有中文）：{len(newtext)} 槽\n')
    by_res = collections.defaultdict(list)
    for item in newtext:
        by_res[item[0]].append(item)
    for res in ('只剩标点（漏译）', '日文假名残留', '拉丁残留', '地址占位符'):
        items = by_res.get(res, [])
        out.write(f'\n### {res}：{len(items)}\n')
        for _r, s, i, src, jp, raw, final, marks in items:
            out.write(f'- {s} idx{i} [{src}] marks={marks}\n')
            out.write(f'    JP {jp}\n    提取 {raw!r}\n    产物 {final}\n')

    for key in ('need-translate', 'crc-tail', 'fix_missing', 'pin_kana',
                'pin_defects', 'pin_variants'):
        items = full_lists.get(key, [])
        out.write(f'\n## 全量：{key}（{len(items)}）\n')
        for s, i, src, jp, raw, final in items:
            out.write(f'- {s} idx{i} [{src}]\n')
            out.write(f'    JP {jp}\n    提取 {raw!r}\n    产物 {final}\n')
            for line in ctx(s, i):
                out.write(f'    {line}\n')

    if others:
        out.write(f'\n## 未能归类的槽（应为 0）：{len(others)}\n')
        for s, i, raw, final in others[:20]:
            out.write(f'- {s} idx{i} 提取 {raw!r} 产物 {final!r}\n')
    out.close()
    print('slots', total, dict(stat), 'newtext', len(newtext),
          dict(collections.Counter(t[0] for t in newtext)))


if __name__ == '__main__':
    main()
