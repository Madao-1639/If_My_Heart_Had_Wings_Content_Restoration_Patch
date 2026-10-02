# -*- coding: utf-8 -*-
"""校验 V-5/V-6 判读交付（tmp/v5_deliveries/{SCRIPT}.jsonl）。

用法：$PY script/check_adjudication.py tmp/v5_deliveries/{SCRIPT}.jsonl [--dump]

检查：JSON 结构 / 块与承载图对得上 / 槽位与原版行全覆盖（每处恰一次）/ 引用反幻觉
（quote 必须逐字出现在对应文本里）。
明细写入 tmp/adjudication_dump.md（UTF-8），控制台只输出 ASCII 摘要。
退出码：0 = 全过；1 = 有失败。
"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
from tool import v5lib  # noqa: E402

ACTIONS = ('keep', 'drop', 'rebind')
DUMP = os.path.join(ROOT, 'tmp', 'adjudication_dump.md')


def orig_text_at(script, i):
    t = v5lib.jp_texts(script)
    if t is not None:
        return t[i].get('text_with_name') or t[i]['text']
    rl = v5lib.rows('orig', script)
    return rl[i]['jp'] if 0 <= i < len(rl) else None


def steam_text_at(script, i):
    rl = v5lib.rows('steam', script)
    return rl[i]['jp'] if 0 <= i < len(rl) else None


def incl_range(a, b):
    """闭区间 [a,b] -> 集合；b<a 视为空。"""
    return set(range(a, b + 1)) if b >= a else set()


def main():
    path = sys.argv[1]
    dump = '--dump' in sys.argv
    script = os.path.basename(path).rsplit('.', 1)[0]
    blks = v5lib.blocks(script)
    by_range = {(tuple(b['orig']) if b.get('orig') else (-1, -2),
                 tuple(b['steam']) if b.get('steam') else (-1, -2)): b for b in blks}
    errs, seen = [], set()
    entries = []
    with open(path, encoding='utf-8') as f:
        for ln, raw in enumerate(f, 1):
            raw = raw.strip()
            if not raw:
                continue
            try:
                e = json.loads(raw)
            except ValueError as ex:
                errs.append('L%d: JSON parse: %s' % (ln, ex))
                continue
            entries.append((ln, e))
            bo = tuple(e.get('block_orig', (-1, -2)))
            bs = tuple(e.get('block_steam', (-1, -2)))
            key = (bo, bs)
            if key not in by_range:
                errs.append('L%d: block %s/%s 不在承载图' % (ln, list(bo), list(bs)))
                continue
            if key in seen:
                errs.append('L%d: 块重复 %s/%s' % (ln, list(bo), list(bs)))
                continue
            seen.add(key)
            b = by_range[key]
            o0, o1 = bo
            s0, s1 = bs
            slots = incl_range(s0, s1)
            orows = incl_range(o0, o1)
            covered_slots, covered_rows = set(), set()
            for c in e.get('cells', []):
                sl = c.get('slot')
                act = c.get('action')
                if sl not in slots:
                    errs.append('L%d: slot %s 不在块内' % (ln, sl))
                    continue
                if sl in covered_slots:
                    errs.append('L%d: slot %s 重复处置' % (ln, sl))
                    continue
                covered_slots.add(sl)
                if act not in ACTIONS:
                    errs.append('L%d: slot %s action 非法: %r' % (ln, sl, act))
                if act == 'rebind':
                    r = c.get('bind_orig_row')
                    if r not in orows:
                        errs.append('L%d: slot %s bind_orig_row %s 不在块内' % (ln, sl, r))
                    else:
                        if r in covered_rows:
                            errs.append('L%d: 原版行 %s 重复绑定' % (ln, r))
                        covered_rows.add(r)
                        ot = orig_text_at(script, r) or ''
                        q = c.get('orig_quote', '')
                        if len(q) < 4 or q not in ot:
                            errs.append('L%d: slot %s orig_quote 反幻觉失败（行 %s）' % (ln, sl, r))
                q = c.get('quote', '')
                st = steam_text_at(script, sl) or ''
                zl = v5lib.zh_official(script)
                zt = zl[sl] if zl and 0 <= sl < len(zl) else ''
                if len(q) < 4 or (q not in st and q not in zt):
                    errs.append('L%d: slot %s quote 反幻觉失败' % (ln, sl))
                if not c.get('form'):
                    errs.append('L%d: slot %s 缺 form' % (ln, sl))
            for ins in e.get('inserts', []):
                a, bi = ins.get('orig_rows', [-1, -2])
                rr = incl_range(a, bi)
                if not rr:
                    errs.append('L%d: insert 区间空 %s' % (ln, ins.get('orig_rows')))
                    continue
                if not rr <= orows:
                    errs.append('L%d: insert 区间越界 %s' % (ln, ins.get('orig_rows')))
                    continue
                if rr & covered_rows:
                    errs.append('L%d: insert 与已处置行重叠' % (ln))
                covered_rows |= rr
                af = ins.get('after_slot')
                if af != 'tail' and not (af == -1 or isinstance(af, int) and s0 - 1 <= af <= s1):
                    errs.append('L%d: insert after_slot 非法: %r' % (ln, af))
            for w in e.get('orig_waived', []):
                a, bi = w if isinstance(w, list) else (-1, -2)
                rr = incl_range(a, bi)
                if not rr <= orows or (rr & covered_rows):
                    errs.append('L%d: waived 区间非法或重叠 %s' % (ln, w))
                covered_rows |= rr
            if covered_slots != slots:
                errs.append('L%d: Steam 槽未全覆盖（缺 %d 处）' % (ln, len(slots - covered_slots)))
            if covered_rows != orows:
                errs.append('L%d: 原版行未全覆盖（缺 %d 行）' % (ln, len(orows - covered_rows)))
            if not e.get('verdict'):
                errs.append('L%d: 缺 verdict' % ln)
    missing = [k for k in by_range if k not in seen]
    for k in missing:
        errs.append('缺块: orig=%s steam=%s' % (list(k[0]), list(k[1])))
    ok = len(seen) - len([e for e in errs if e.startswith('L') or e.startswith('缺')])
    # 明细
    if dump:
        lines = ['# 判读校验明细 — %s' % script, '', '- 交付：%s' % path, '']
        for ln, e in entries:
            lines += ['## L%d · %s %s' % (ln, e.get('verdict', ''), e.get('note', '')), '',
                      '```json', json.dumps(e, ensure_ascii=False, indent=1), '```', '']
        with open(DUMP, 'w', encoding='utf-8') as f:
            f.write('\n'.join(lines))
    n_err = len(errs)
    print('script %s: blocks %d checked, errors %d, missing-blocks %d' %
          (script, len(seen), n_err, len(missing)))
    for m in errs[:20]:
        print('  ' + m.encode('ascii', 'replace').decode('ascii'))
    if dump and n_err == 0:
        print('dump: %s' % DUMP)
    sys.exit(0 if n_err == 0 else 1)


if __name__ == '__main__':
    main()
