# -*- coding: utf-8 -*-
"""产出端：语音同名冲突判定表 `resource/voice_conflict_map.json`。

判据（与图像侧 `censor_map.json` 同构：入库表只认证据，动作只有 overwrite / keep）：

- 比对范围＝两侧 `VOICE.arc` 里**大小写折叠同名、SHA256 不同**的 `.OGG` 成员。
- 解码两侧（ffmpeg → 8 kHz 单声道 PCM），按**同一录音是否被改动**分三类：
  - `noise`    ：解码 PCM 实质相同（等长逐字节相同，或最佳对齐后相关 >= 0.98）⇒ 仅容器差；
  - `recode`   ：最佳对齐后相关 >= 0.5（同一录音，被重编码／剪辑，时长常变）;
  - `rerecord` ：最佳对齐后相关 < 0.5（换录音）。
- 动作：`noise` ⇒ `keep`（不动）；`recode`／`rerecord` ⇒ `overwrite`（整名覆盖回原版字节）。

无 ffmpeg 时退化为**容器级**判据（时长／vendor／体积全同 ⇒ noise），条目记 `review='container-only'`。

消费方：`script/build/build_restore_plan.py`（把 `action=overwrite` 子集**逐名**并入
`resources.overwrite`，不以「被还原内容引用」为门槛——口径见 doc/resource-naming.md §1／§3）。
"""
import argparse
import array
import hashlib
import json
import math
import os
import shutil
import struct
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
from tool import arcbuild  # noqa: E402

OUT = os.path.join(ROOT, 'resource', 'voice_conflict_map.json')
RATE = 8000
WIN = 40          # 5 ms 包络帧
ALIGN_WIN = 8000  # 相关窗上限（1 s）
NOISE_CORR = 0.98
RECODE_CORR = 0.50


def find_ffmpeg(explicit=''):
    for c in (explicit, os.environ.get('FFMPEG', ''), shutil.which('ffmpeg') or '',
              r'D:\ffmpeg\bin\ffmpeg.exe'):
        if c and os.path.exists(c):
            return c
    return ''


def members(path):
    """{小写名: (原名, 数据)}"""
    out = {}
    for nb, data in arcbuild.read_raw(path):
        nm = nb.decode('utf-16-le')
        out[nm.lower()] = (nm, data)
    return out


def ogg_info(blob):
    """纯 Python 读 OGG：总采样数(末页 granule)、采样率、声道、vendor。"""
    samples = rate = ch = None
    vendor = None
    p = 0
    n = len(blob)
    while p + 27 <= n:
        if blob[p:p + 4] != b'OggS':
            break
        seg = blob[p + 26]
        if p + 27 + seg > n:
            break
        g = struct.unpack_from('<q', blob, p + 6)[0]
        if g >= 0:
            samples = g
        q = p + 27
        total = 0
        for i in range(seg):
            total += blob[q + i]
        body = q + seg
        if rate is None and body + 16 <= n and blob[body + 1:body + 7] == b'vorbis':
            ch = blob[body + 11]
            rate = struct.unpack_from('<I', blob, body + 12)[0]
        if vendor is None:
            k = blob.find(b'\x03vorbis', body, min(n, body + 4096))
            if k >= 0 and k + 11 <= n:
                vl = struct.unpack_from('<I', blob, k + 7)[0]
                vendor = blob[k + 11:k + 11 + vl].decode('utf-8', 'replace')
        p = body + total
    dur = (samples / rate) if (samples and rate) else None
    return {'dur': dur, 'rate': rate, 'ch': ch, 'vendor': vendor, 'bytes': len(blob)}


def decode(ffmpeg, blob):
    r = subprocess.run([ffmpeg, '-v', 'error', '-i', 'pipe:0', '-f', 's16le',
                        '-ac', '1', '-ar', str(RATE), '-'],
                       input=blob, capture_output=True)
    a = array.array('h')
    a.frombytes(r.stdout)
    return a


def envelope(a):
    return [math.sqrt(sum(a[i + j] * a[i + j] for j in range(WIN)) / WIN)
            for i in range(0, len(a) - WIN, WIN)]


def align_env(e1, e2):
    """粗对齐（步长 4 帧）→ 精修（±4 帧）。返回 (corr, lag帧)。"""
    n1, n2 = len(e1), len(e2)
    m1 = sum(e1) / n1
    m2 = sum(e2) / n2
    lo = -(n2 - max(5, n2 // 3))
    hi = n1 - max(5, n1 // 3)

    def c(lag):
        s = a1 = a2 = 0.0
        cnt = 0
        for i in range(n1):
            j = i - lag
            if 0 <= j < n2:
                x = e1[i] - m1
                y = e2[j] - m2
                s += x * y
                a1 += x * x
                a2 += y * y
                cnt += 1
        return (s / math.sqrt(a1 * a2)) if (cnt > 20 and a1 > 0 and a2 > 0) else -9.0

    best, bl = -9.0, 0
    for lag in range(lo, hi, 4):
        v = c(lag)
        if v > best:
            best, bl = v, lag
    for lag in range(bl - 4, bl + 5):
        v = c(lag)
        if v > best:
            best, bl = v, lag
    return best, bl


def best_raw_corr(A, B, lag_frames, span=200):
    """在包络滞后 ±span 采样（±25 ms）内以 **1 采样**步长精修原始 PCM 相关。

    包络分辨率 5 ms ⇒ 粗滞后误差 ≤ 约 10 ms，±25 ms 足以覆盖；窗口取重叠区中心 1 s。
    """
    n1, n2 = len(A), len(B)
    base = lag_frames * WIN

    def c(lag):
        i0 = max(0, lag)
        i1 = min(n1, n2 + lag)
        if i1 - i0 < 200:
            return -9.0
        mid = (i0 + i1) // 2
        s0 = max(i0, mid - ALIGN_WIN // 2)
        s1 = min(i1, mid + ALIGN_WIN // 2)
        num = a1 = a2 = 0.0
        for i in range(s0, s1):
            x = A[i]
            y = B[i - lag]
            num += x * y
            a1 += x * x
            a2 += y * y
        return (num / math.sqrt(a1 * a2)) if (a1 and a2) else -9.0

    best, bl = -9.0, base
    for lag in range(base - span, base + span + 1):
        v = c(lag)
        if v > best:
            best, bl = v, lag
    return best, bl


def classify(ffmpeg, sb, ob, isb, iob):
    """返回 (class, action, evidence, review)。"""
    ev = {'steam_bytes': len(sb), 'orig_bytes': len(ob),
          'steam_dur': round(isb['dur'], 3) if isb['dur'] else None,
          'orig_dur': round(iob['dur'], 3) if iob['dur'] else None,
          'steam_vendor': isb['vendor'], 'orig_vendor': iob['vendor']}
    if ev['steam_dur'] is not None and ev['orig_dur'] is not None:
        ev['d_dur'] = round(ev['orig_dur'] - ev['steam_dur'], 3)
    if not ffmpeg:
        same = (ev['steam_bytes'] == ev['orig_bytes'] and ev['steam_dur'] == ev['orig_dur']
                and ev['steam_vendor'] == ev['orig_vendor'])
        ev['method'] = 'container-only'
        return ('noise' if same else 'content'), ('keep' if same else 'overwrite'), ev, 'container-only'
    A, B = decode(ffmpeg, sb), decode(ffmpeg, ob)
    ev['method'] = 'pcm'
    if len(A) == len(B) and A.tobytes() == B.tobytes():
        ev['env_corr'] = 1.0
        ev['pcm_corr'] = 1.0
        ev['lag_ms'] = 0.0
        return 'noise', 'keep', ev, 'machine'
    ec, lag = align_env(envelope(A), envelope(B))
    rc, rl = best_raw_corr(A, B, lag)
    ev['env_corr'] = round(ec, 3)
    ev['pcm_corr'] = round(rc, 3)
    ev['lag_ms'] = round(rl / RATE * 1000, 1)
    # 「噪声」＝**解码音频实质相同**：既要相关达 0.98，也要时长一致（<=0.15 s）。
    # 只看相关会漏判「同一录音被剪掉一截」（重叠段相关仍近 1，但时长差大）——
    # 那属内容差，必须覆盖（AGE_3941 剪 1.50 s、YOR_1659 剪 0.94 s）。
    d_dur = abs(ev.get('d_dur') or 0.0)
    if rc >= NOISE_CORR and d_dur <= 0.15:
        return 'noise', 'keep', ev, 'machine'
    if rc >= RECODE_CORR:
        return 'recode', 'overwrite', ev, 'machine'
    return 'rerecord', 'overwrite', ev, 'machine'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--orig-dir', default=os.environ.get('IFMH_ORIG_DIR', ''))
    ap.add_argument('--backup', default=os.path.join(ROOT, 'backup'))
    ap.add_argument('--ffmpeg', default='')
    ap.add_argument('--out', default=OUT)
    args = ap.parse_args()
    if not args.orig_dir or not os.path.isdir(args.orig_dir):
        sys.stderr.write('need --orig-dir (or IFMH_ORIG_DIR)\n')
        return 2
    ffmpeg = find_ffmpeg(args.ffmpeg)
    if not ffmpeg:
        sys.stderr.write('WARN: ffmpeg not found -> container-only classification\n')

    S = members(os.path.join(args.backup, 'VOICE.arc'))
    O = members(os.path.join(args.orig_dir, 'VOICE.arc'))
    common = sorted(set(S) & set(O))
    diff = [k for k in common if hashlib.sha256(S[k][1]).digest() != hashlib.sha256(O[k][1]).digest()]
    print('members: steam %d orig %d common %d ; byte-diff %d' % (len(S), len(O), len(common), len(diff)))

    rows = []
    for i, k in enumerate(diff, 1):
        sn, sb = S[k]
        on, ob = O[k]
        cls, act, ev, rev = classify(ffmpeg, sb, ob, ogg_info(sb), ogg_info(ob))
        rows.append({'name': sn, 'orig_name': on, 'archive': 'VOICE.arc',
                     'class': cls, 'action': act, **ev, 'review': rev})
        print('  [%2d/%d] %-16s %-9s -> %s' % (i, len(diff), sn, cls, act))

    rows.sort(key=lambda r: (r['class'], r['name']))
    cnt = {}
    for r in rows:
        cnt[r['class']] = cnt.get(r['class'], 0) + 1
    doc = {
        'meta': {
            'spec': 'doc/resource-naming.md §3',
            'producer': 'script/build/build_voice_conflict_map.py',
            'consumer': 'script/build/build_restore_plan.py',
            'method': '两侧 VOICE.arc 大小写折叠同名 ∧ SHA256 不同 ⇒ 解码 8k 单声道 PCM，'
                      '包络粗对齐 + 1 采样精修求原始 PCM 相关；'
                      'corr>=0.98 => noise（仅容器差）、>=0.5 => recode（同录音被重编码/剪辑）、'
                      '<0.5 => rerecord（换录音）',
            'class_values': ['noise', 'recode', 'rerecord'],
            'actions': {'overwrite': '整名覆盖回原版字节（名字与表位置不变）',
                        'keep': '噪声，不动'},
            'gate': '写盘器只替换名单内成员；名单数必须等于替换数（script/build/build_patch.py 断言）',
            'archives': ['VOICE.arc'],
        },
        'summary': {'byte_diff': len(rows), **cnt,
                    'overwrite': sum(1 for r in rows if r['action'] == 'overwrite'),
                    'keep': sum(1 for r in rows if r['action'] == 'keep')},
        'members': rows,
    }
    with open(args.out, 'w', encoding='utf-8', newline='\n') as f:
        json.dump(doc, f, ensure_ascii=False, indent=1)
        f.write('\n')
    print('wrote %s : %s' % (args.out, doc['summary']))
    return 0


if __name__ == '__main__':
    sys.exit(main())
