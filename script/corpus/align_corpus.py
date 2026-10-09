"""位置对齐：原版脚本全文本行 A ←→ 民间汉化表 B（AdvPatch.dll PAK/#101）。

结论依据（doc/script-text-extraction.md §2.1）：民汉表不是键值表，而是汉化组
按 A 的顺序逐行铺出的**位置序列**——同一 CRC32 的多次出现各自带不同译文，
必须按位置而不是按键消费。A = 全部原版脚本的文本行（脚本名字典序、脚本内
字节序、含 %LC 角色名行），实测 87,355 行；B = 表内 87,342 条。

算法：
  1. 锚点 = 两侧都唯一的 CRC32；对锚点取 LIS 得单调骨架。
  2. 骨架之间用局部 Needleman-Wunsch（match +2 / 失配 -4 即禁对角 / 空 gap
     -1）逐格对齐，得到 A→B 的位置配对。
  3. 落空的 A 行（菜单标签、FLAG_CHECK 标签、%K 结尾行等在表尾部另成块的）
     按 CRC32 在未消费的 B 行里认领，取索引最小者。
  4. 仍无译文的 A 行标 src=need-translate，由构建阶段就地补译（禁止回退日文）。

产物 resource/corpus/pairing.jsonl：每行
  {script, kind, idx, off, seq, jp, cn, src}
  src ∈ positional | crc-tail | ctrl | need-translate
"""
import argparse
import bisect
import collections
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from tool import scriptext  # noqa: E402

MATCH, GAP = 2.0, -1.0
DEFAULT_OUT = ROOT / 'resource' / 'corpus' / 'pairing.jsonl'


def load_table(path):
    """民汉表 B：[(crc32, text)]，保持 dump 序（=铺表序）。"""
    out = []
    with open(path, 'r', encoding='utf-8') as f:
        for line in f:
            e = json.loads(line)
            out.append((e['crc32'], e['text']))
    return out


def skeleton(a_crc, b_crc):
    """两侧唯一 CRC32 的锚点，取其 b 坐标的 LIS 作单调骨架。"""
    pos_b, dup_b = {}, set()
    for i, c in enumerate(b_crc):
        if c in pos_b:
            dup_b.add(c)
        else:
            pos_b[c] = i
    cnt_a = collections.Counter(c for c in a_crc if c is not None)
    anchors = sorted((i, pos_b[c]) for i, c in enumerate(a_crc)
                     if c is not None and cnt_a[c] == 1 and c in pos_b and c not in dup_b)
    tails, tpos, prev = [], [], []
    for idx, (_a, b_i) in enumerate(anchors):
        k = bisect.bisect_left(tails, b_i)
        prev.append(tpos[k - 1] if k else -1)
        if k == len(tails):
            tails.append(b_i)
            tpos.append(idx)
        else:
            tails[k] = b_i
            tpos[k] = idx
    skel = []
    if tpos:
        p = tpos[len(tails) - 1]
        while p != -1:
            skel.append(anchors[p])
            p = prev[p]
    skel.reverse()
    return anchors, skel


def nw(a_crc, b_crc, a_lo, a_hi, b_lo, b_hi):
    """A[a_lo:a_hi] ↔ B[b_lo:b_hi] 的对齐；返回 [(a, b|None), ...]。"""
    na, nb = a_hi - a_lo, b_hi - b_lo
    neg = float('-inf')
    dp = [[neg] * (nb + 1) for _ in range(na + 1)]
    bt = [[0] * (nb + 1) for _ in range(na + 1)]
    dp[0][0] = 0.0
    for i in range(1, na + 1):
        dp[i][0] = dp[i - 1][0] + GAP
        bt[i][0] = 1
    for j in range(1, nb + 1):
        dp[0][j] = dp[0][j - 1] + GAP
        bt[0][j] = 2
    for i in range(1, na + 1):
        ai = a_crc[a_lo + i - 1]
        for j in range(1, nb + 1):
            best, op = dp[i][j], 0
            d = dp[i - 1][j] + GAP
            if d > best:
                best, op = d, 1
            d = dp[i][j - 1] + GAP
            if d > best:
                best, op = d, 2
            if ai is not None and ai == b_crc[b_lo + j - 1]:
                d = dp[i - 1][j - 1] + MATCH
                if d > best:
                    best, op = d, 3
            dp[i][j], bt[i][j] = best, op
    pairs = []
    i, j = na, nb
    while i or j:
        op = bt[i][j]
        if op == 3:
            pairs.append((a_lo + i - 1, b_lo + j - 1))
            i -= 1
            j -= 1
        elif op == 1:
            pairs.append((a_lo + i - 1, None))
            i -= 1
        elif op == 2:
            j -= 1
        else:
            break
    pairs.reverse()
    return pairs


def align(A, B):
    """A（含 crc 字段）↔ B（(crc, text)）→ 每条 A 的 (b, src)。"""
    a_crc = [r['crc'] for r in A]
    b_crc = [c for c, _t in B]
    anchors, skel = skeleton(a_crc, b_crc)
    pair = {}
    pa = pb = -1
    for a_i, b_i in skel:
        for ai, bi in nw(a_crc, b_crc, pa + 1, a_i, pb + 1, b_i):
            pair[ai] = bi
        pair[a_i] = b_i
        pa, pb = a_i, b_i
    for ai, bi in nw(a_crc, b_crc, pa + 1, len(A), pb + 1, len(B)):
        pair[ai] = bi

    used = {b for b in pair.values() if b is not None}
    free = collections.defaultdict(collections.deque)
    for i in range(len(B)):
        if i not in used:
            free[b_crc[i]].append(i)

    out = []
    for i, r in enumerate(A):
        b = pair.get(i)
        if b is not None:
            out.append((b, 'positional'))
        elif r['kind'] == 'ctrl':
            out.append((None, 'ctrl'))
        else:
            q = free.get(r['crc'])
            if q:
                out.append((q.popleft(), 'crc-tail'))
            else:
                out.append((None, 'need-translate'))
    return out, used, skel, anchors


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--orig-dir', help='原版素材目录（含 Rio.arc 与 RIO/），缺省取环境变量 IFMH_ORIG_DIR')
    ap.add_argument('--table', help='民汉译文表 extracted_text.jsonl，缺省取环境变量 IFMH_CORPUS_TABLE')
    ap.add_argument('--out', default=str(DEFAULT_OUT))
    args = ap.parse_args()

    orig_dir = args.orig_dir or scriptext.DEFAULT_ORIG_DIR
    table = args.table or scriptext.DEFAULT_TABLE
    if not orig_dir or not table:
        sys.exit(f'素材路径未提供：--orig-dir / --table，或环境变量 '
                 f'{scriptext.IFMH_ORIG_DIR} / {scriptext.IFMH_CORPUS_TABLE}'
                 f'（素材来源见 doc/restoration-targets.md）')

    A = scriptext.all_rows(orig_dir)
    B = load_table(table)
    print(f'A rows {len(A)}  ({collections.Counter(r["kind"] for r in A)})')
    print(f'B rows {len(B)}')

    out, used, skel, anchors = align(A, B)
    stat = collections.Counter(s for _b, s in out)
    consumed = {b for b, _s in out if b is not None} | used
    print('source distribution', dict(stat))
    print(f'B consumed {len(consumed)}/{len(B)}, left {len(B) - len(consumed)}')

    rows = []
    for r, (b, src) in zip(A, out):
        cn = '' if b is None else B[b][1]
        if src == 'ctrl':
            cn = '%P'
        rows.append({'script': r['script'], 'kind': r['kind'], 'idx': r['idx'],
                     'off': r['off'], 'seq': r['seq'], 'jp': r['jp'], 'cn': cn,
                     'src': src, 'crc': r['crc']})
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    with open(args.out, 'w', encoding='utf-8') as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + '\n')
    print('anchors', len(anchors), 'LIS skeleton', len(skel))
    print(f'wrote {args.out}: {len(rows)} rows')
    need = [r for r in rows if r['src'] == 'need-translate']
    print('need-translate rows', len(need))
    for r in need:
        print(f'  {r["script"]} idx={r["idx"]} kind={r["kind"]} crc={r["crc"]}')


if __name__ == '__main__':
    main()
