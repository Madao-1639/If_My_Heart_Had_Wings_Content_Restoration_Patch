"""把位置对齐后的中日对照（resource/corpus/pairing.jsonl）组装为逐脚本 JSON 产物（默认 `resource/fan_cn/`）。

数据来源与口径（doc/script-text-extraction.md §2.1）：
  - 民汉表（AdvPatch.dll 内 PAK/#101，87,342 条）是汉化组按原版脚本全文本行
    顺序**逐行铺出的位置序列**，不是键值表。因此中文取自
    script/corpus/align_corpus.py 的 A↔B 位置配对，而不是"同一 CRC32 的第 N 次出现"。
  - 逐行译文先过 tool/textfix.normalize（机械层：剥工作批注、剥注音、术语
    统一、繁转简、假名残留清理），再套 resource/corpus/review_fixes.jsonl（语境层：
    并发评审 subagent 的逐行修正 + 漏译就地补译）。

产物（resource/fan_cn/，主存储 = 逐脚本 JSON）：
  {SCRIPT}.json   idx → 中文文本 的扁平映射（一行一条；对白/菜单/FLAG_CHECK/
                  清屏行共用同一 idx 命名空间，缺失 key = 该槽无行）。
                  日文对照不在此重复存，见 resource/corpus/pairing.jsonl。
  NameTable.json  角色名映射（%LC<日文名> → 中文显示名）
  manifest.json   逐脚本槽位数/来源分布/修正条数 + 总量 + 验收比对（不含文本）

引擎装载形态 .lng（XOR 0x88）/NameTable.txt 不留档，只在临时试装时派生到 tmp：
  python script/corpus/build_fan_translations.py --emit-lng [--lng-out tmp/lng_emit]
  （条目数 = max idx + 1，空洞为空串 = 引擎回退脚本内嵌原文；当前 G1 门禁下无空洞）

槽位规则：
  1. lng 条目按 \\x14 的 idx 索引；size = max(对白 idx ∪ 菜单 id ∪ FLAG_CHECK id)+1。
  2. 空 speaker 的清屏行（kind=ctrl）按官方形态填 '%P'。
  3. 菜单/FLAG_CHECK 标签写进各自 id 槽位，无 %K/%P。
  4. %LC 角色名不进正文产物，进 NameTable.json（--emit-lng 时另出引擎用 NameTable.txt）。

硬约束（违反即构建失败，逐站点列出）：
  G1 有实义内容的对白/标签不得没有中文（漏译必须就地补译，禁止回退日文）
  G2 中文不得残留日文假名、`{正文:读音}` 注音、【润色】类工作批注
  G3 产物写入后按同 key 回读必须逐条相等（JSON 序列化-回读断言；--emit-lng 时另加 lng 编解码断言）
"""
import argparse
import collections
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from tool import lng as lng_codec  # noqa: E402
from tool import scriptext, textfix  # noqa: E402

DEFAULT_PAIRING = ROOT / 'resource' / 'corpus' / 'pairing.jsonl'
DEFAULT_FIXES = ROOT / 'resource' / 'corpus' / 'review_fixes.jsonl'
DEFAULT_OUTPUT = ROOT / 'resource' / 'fan_cn'
DEFAULT_LEGACY = ROOT / 'resource' / 'corpus' / 'zh'


def repo_rel(path):
    """仓库内的路径写成 POSIX 相对形式，清单里不落本机绝对路径。"""
    p = Path(path).resolve()
    return p.relative_to(ROOT).as_posix() if p.is_relative_to(ROOT) else p.as_posix()


KANA_RE = re.compile(r'[぀-ヿｦ-ﾟ]')
RUBY_RE = re.compile(r'\{[^{}]*[:：][^{}]*\}')
NOTE_RES = (textfix.WORK_NOTE, textfix.WORK_NOTE_PAREN, textfix.WORK_NOTE_STAR)
# 引擎控制标记：%K 等待点击 / %P 清屏翻页（决定对话流程，必须与日文一致）；
# 字面 \n 是强制换行（中文行长与日文不同，少一个只影响美观，不阻断）
FLOW_RE = re.compile(r'%K|%P')
BREAK_RE = re.compile(r'\\n')
LEADER_RE = re.compile(r'^(?:%LC|%XS\d+)*')
HAN_RE = re.compile(r'[㐀-䶿一-鿿]')
# 民汉表里被表内地址/序号占位符污染的条目（形如 ●000824●●、%LC●小）：
# 不含假名、也不是空串，G1/G2/G6 都拦不住，必须单独设门禁
PLACEHOLDER_RE = re.compile(r'●')

# "有实义内容" = 存在控制标记、空白、引号之外的字符
_CONTENT_RE = re.compile(r'[^\s%KP\\n「」『』（）()【】…—－-]+')


def has_content(text):
    return bool(text) and bool(_CONTENT_RE.search(text))


def load_pairing(path):
    """resource/corpus/pairing.jsonl → 按脚本分组的行。"""
    by_script = collections.OrderedDict()
    with open(path, 'r', encoding='utf-8') as f:
        for line in f:
            r = json.loads(line)
            by_script.setdefault(r['script'], []).append(r)
    return by_script


def load_fixes(path):
    """语境层修正：{(script, idx): cn}；文件不存在时为空（首次构建可跳过）。"""
    if not Path(path).exists():
        return {}
    fixes = {}
    with open(path, 'r', encoding='utf-8') as f:
        for line in f:
            e = json.loads(line)
            fixes[(e['script'], e['idx'])] = e['cn']
    return fixes


def load_legacy_totals(path):
    """resource/corpus/zh/{SCRIPT}.json 的 total（旧口径逐脚本条目数，仅作验收对照）。"""
    out = {}
    dec = json.JSONDecoder()
    path = Path(path)
    if not path.is_dir():
        return out
    for p in sorted(path.glob('*.json')):
        try:
            d, _ = dec.raw_decode(p.read_text('utf-8'))
        except (ValueError, KeyError):
            continue
        out[d['script']] = d.get('total')
    return out


def name_display(cn, jp):
    """NameTable 显示名：查点名表 → 剥掉值里的 %LC 前缀 → 归一化。"""
    if jp in textfix.NAME_FIX:
        return textfix.NAME_FIX[jp]
    v = (cn or '').strip()
    if v.startswith('%LC'):
        v = v[3:]
    v = textfix.normalize(v)
    v = re.sub(r'[%P\s]+$', '', v)
    return v or jp[3:]


def build_script(rows, fixes, violations, soft):
    """单脚本 → (lng 条目列表, name 映射候选, 统计)。"""
    entries = {}
    names = collections.defaultdict(collections.Counter)
    src_count = collections.Counter()
    tally = collections.Counter()
    n_fix = 0
    n_soft_break = 0

    for r in rows:
        kind, idx = r['kind'], r['idx']
        src_count[r['src']] += 1
        if kind == 'name':
            names[r['jp']][r['cn']] += 1
            continue
        if kind == 'ctrl':
            entries[idx] = '%P'
            continue
        jp = r['jp']
        fixed = fixes.get((r['script'], idx))
        cn = textfix.emit(jp, r['cn'] or '', fixed, tally)
        if fixed is not None:
            src_count['review-fix'] += 1
            n_fix += 1
        if not has_content(cn) and (HAN_RE.search(jp) or not FLOW_RE.sub('', cn).strip()):
            violations.append((r['script'], idx, kind, 'G1-empty', cn, jp))
        if KANA_RE.search(cn):
            violations.append((r['script'], idx, kind, 'G2-kana', cn, jp))
        if RUBY_RE.search(cn):
            violations.append((r['script'], idx, kind, 'G2-ruby', cn, jp))
        for rx in NOTE_RES:
            if rx.search(cn):
                violations.append((r['script'], idx, kind, 'G2-note', cn, jp))
        if PLACEHOLDER_RE.search(cn):
            violations.append((r['script'], idx, kind, 'G7-placeholder', cn, jp))
        if cn.count('「') != cn.count('」') and jp.count('「') == jp.count('」'):
            violations.append((r['script'], idx, kind, 'G8-bracket', cn, jp))
        if FLOW_RE.findall(jp) != FLOW_RE.findall(cn):
            violations.append((r['script'], idx, kind, 'G4-flow', cn, jp))
        lj, lc = LEADER_RE.match(jp).group(0), LEADER_RE.match(cn).group(0)
        if lj and lj != lc:
            violations.append((r['script'], idx, kind, 'G5-leader', cn, jp))
        nb_j, nb_c = len(BREAK_RE.findall(jp)), len(BREAK_RE.findall(cn))
        if nb_j or nb_c:
            soft.append((r['script'], idx, nb_j, nb_c, jp, cn))
            if nb_j != nb_c:
                n_soft_break += 1
        entries[idx] = cn

    size = (max(entries) + 1) if entries else 0
    texts = [entries.get(i, '') for i in range(size)]
    stat = {
        'size': size,
        'terminator_aligned': tally['terminator_aligned'],
        'bracket_balanced': tally['bracket_balanced'],
        'soft_break_diff': n_soft_break,
        'n_dlg': sum(1 for r in rows if r['kind'] == 'dlg'),
        'n_menu': sum(1 for r in rows if r['kind'] == 'menu'),
        'n_flag': sum(1 for r in rows if r['kind'] == 'flag'),
        'n_ctrl': sum(1 for r in rows if r['kind'] == 'ctrl'),
        'n_name_row': sum(1 for r in rows if r['kind'] == 'name'),
        'n_unique_name': len(names),
        'src': {k: v for k, v in sorted(src_count.items())},
        'review_fixes': n_fix,
    }
    return texts, entries, names, stat


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--pairing', default=str(DEFAULT_PAIRING))
    ap.add_argument('--fixes', default=str(DEFAULT_FIXES))
    ap.add_argument('--output', default=str(DEFAULT_OUTPUT))
    ap.add_argument('--legacy', default=str(DEFAULT_LEGACY))
    args = ap.parse_args()

    out_dir = Path(args.output)
    out_dir.mkdir(parents=True, exist_ok=True)

    by_script = load_pairing(args.pairing)
    fixes = load_fixes(args.fixes)
    legacy = load_legacy_totals(args.legacy)
    print(f'pairing: {args.pairing}  scripts={len(by_script)}')
    print(f'review fixes: {len(fixes)} slots ({args.fixes})')

    violations, soft = [], []
    manifest = {
        'generator': 'script/corpus/build_fan_translations.py',
        'pairing': repo_rel(args.pairing),
        'pairing_doctrine': ('positional: the fan table (AdvPatch.dll PAK/#101) is a '
                             'line-by-line dump of the original script text sequence, so '
                             'each Chinese entry is taken from its aligned slot, not from '
                             'the Nth occurrence of a crc32 key'),
        'text_layer': {
            'mechanical': 'tool/textfix.normalize (work-notes, ruby, term map, trad->simp, kana residue)',
            'contextual': 'resource/corpus/review_fixes.jsonl (concurrent per-script semantic review + in-place translation of gaps)',
        },
        'key': '0x88 (Steam official zh-CN)',
        'conventions': {
            'dialogue': 'entry keeps %K/%P markers, like official zh-CN lng',
            'menu': 'bare label at its 0x0f option id slot, no %K/%P',
            'flagcheck': 'label at its FLAG_CHECK id slot; non-ASCII-validated so binary noise no longer inflates slots',
            'empty_ctrl': "'%P' for speaker-less clear-box lines (official convention)",
            'names': 'not in per-script text; see NameTable.json (engine NameTable.txt is built at patch-write time by script/build/build_nametable.py)',
            'fallback': 'none: every content-bearing line must carry Chinese (build gate G1)',
        },
        'totals': {},
        'scripts': {},
        'acceptance': {},
    }
    tot = collections.Counter()
    name_rows = collections.defaultdict(collections.Counter)
    name_jp_order = []
    pending = []

    for name, rows in by_script.items():
        texts, entries, names, stat = build_script(rows, fixes, violations, soft)
        if not texts:
            tot['scripts_empty_skipped'] += 1
            continue
        doc = {str(i): entries[i] for i in sorted(entries)}
        blob = json.dumps(doc, ensure_ascii=False, indent=1)
        assert json.loads(blob) == doc, f'{name}: json round-trip mismatch (G3)'
        pending.append((name, blob))

        for jp, cnt in names.items():
            if jp not in name_rows:
                name_jp_order.append(jp)
            name_rows[jp].update(cnt)

        tot['scripts'] += 1
        tot['entries'] += stat['size']
        tot['written'] += len(doc)
        stat['entries_written'] = len(doc)
        tot['terminator_aligned'] += stat['terminator_aligned']
        tot['bracket_balanced'] += stat['bracket_balanced']
        tot['soft_break_diff'] += stat['soft_break_diff']
        for k in ('n_dlg', 'n_menu', 'n_flag', 'n_ctrl', 'n_name_row'):
            tot[k] += stat[k]
        tot['review_fixes_applied'] += stat['review_fixes']
        stat['legacy_total'] = legacy.get(name)
        stat['size_matches_legacy'] = (stat['size'] == legacy.get(name)) \
            if name in legacy else None
        manifest['scripts'][name] = stat

    # NameTable 条目先算：日文说话名会直接上屏，必须入门禁
    name_entries, identity = [], 0
    for jp in name_jp_order:
        cn = name_rows[jp].most_common(1)[0][0]
        display = name_display(cn, jp)
        if display == jp[3:]:
            identity += 1
        if not display.strip() or KANA_RE.search(display) or PLACEHOLDER_RE.search(display):
            violations.append(('NameTable', jp, 'name', 'G6-name', display, jp))
        name_entries.append((jp, display))

    gate_report = ROOT / 'tmp' / 'build_gates.md'
    gate_report.parent.mkdir(parents=True, exist_ok=True)
    by_code = collections.Counter(v[3] for v in violations)
    L = ['# 构建门禁报告', '',
         f'- 违规 {len(violations)} 行：' + (', '.join(f'{k} {v}' for k, v in by_code.most_common()) or '无'),
         f'- 软换行 \\n 数量与日文不同 {tot["soft_break_diff"]} 行（信息性，不阻断：中文行长与日文不同，少一个强制换行只影响美观）',
         f'- 行尾 %K/%P 组合按日文校正 {tot["terminator_aligned"]} 行',
         f'- 落单引号修平 {tot["bracket_balanced"]} 行', '',
         '## 违规明细']
    for s, i, k, code, cn, jp in violations:
        L.append(f'- {s} idx{i} ({k}) [{code}]')
        L.append(f'    JP {jp}')
        L.append(f'    CN {cn}')
    L.append('')
    L.append('## 软换行差异明细')
    for s, i, nj, nc, jp, cn in soft:
        if nj != nc:
            L.append(f'- {s} idx{i} (JP {nj} / CN {nc})')
            L.append(f'    JP {jp}')
            L.append(f'    CN {cn}')
    gate_report.write_text('\n'.join(L) + '\n', encoding='utf-8')

    if violations:
        detail = ', '.join(f'{k} {v}' for k, v in by_code.most_common())
        lines = '\n'.join(f'  {s} idx{i} [{c}] CN={cn!r}'
                          for s, i, _k, c, cn, _j in violations[:20])
        raise RuntimeError(f'build gates failed ({len(violations)} slots: {detail})'
                           f' — see {gate_report}\n{lines}')

    name_map = {jp: display for jp, display in name_entries}
    (out_dir / 'NameTable.json').write_text(
        json.dumps(name_map, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')

    for name, blob in pending:
        (out_dir / f'{name}.json').write_text(blob + '\n', encoding='utf-8')
    fresh = {f'{name}.json' for name, _b in pending} | {'NameTable.json'}
    stale = sorted(p.name for p in out_dir.glob('*.json')
                   if p.name not in fresh and p.name != 'manifest.json')
    if stale:
        print(f'[WARN] {len(stale)} .json in output dir not produced by this build '
              f'(stale or hand-placed): {stale[:10]}')

    dl = tot['n_dlg'] or 1
    src_all = collections.Counter()
    for st in manifest['scripts'].values():
        for k, v in st['src'].items():
            src_all[k] += v
    size_diff = sorted(s for s, st in manifest['scripts'].items()
                       if st['size_matches_legacy'] is False)
    manifest['totals'] = {
        'scripts_with_output': tot['scripts'],
        'scripts_empty_skipped': tot['scripts_empty_skipped'],
        'slot_space': tot['entries'],
        'json_entries_written': tot['written'],
        'dialogue': tot['n_dlg'],
        'clear_lines': tot['n_ctrl'],
        'menu_labels': tot['n_menu'],
        'flagcheck_labels': tot['n_flag'],
        'name_rows': tot['n_name_row'],
        'unique_names': len(name_entries),
        'nametable_identity': identity,
        'review_fixes_applied': tot['review_fixes_applied'],
        'terminator_aligned': tot['terminator_aligned'],
        'bracket_balanced': tot['bracket_balanced'],
        'soft_break_diff': tot['soft_break_diff'],
        'cn_source_distribution': dict(src_all),
    }
    manifest['acceptance'] = {
        'per_script_size_vs_legacy_extraction': {
            'compared': len(legacy),
            'mismatch': size_diff,
            'note': ('legacy = resource/corpus/zh/*.json, produced by the retired per-key '
                     'walker; mismatch means the slot count differs, not that text '
                     'is missing'),
        },
        'gates': {
            'G1_empty': 0,
            'G2_kana_ruby_note': 0,
            'G3_roundtrip': 'all scripts',
            'G4_flow_markers': '0 (JP/CN %K/%P sequences identical)',
            'G5_leader': '0 (%LC/%XS prefix parity)',
            'G6_name': '0 (NameTable display has no Japanese name / placeholder)',
            'G7_placeholder': '0 (no table-address residue like ●000824●●)',
        },
    }
    (out_dir / 'manifest.json').write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')

    print()
    for k, v in manifest['totals'].items():
        print(f'  {k}: {v}')
    print(f'  size_vs_legacy mismatch: {len(size_diff)} {size_diff[:10]}')
    print(f'output: {out_dir}')


if __name__ == '__main__':
    main()
