# -*- coding: utf-8 -*-
"""全归档资源清单差分：成员名集合差 + 同名成员 SHA256 对比。

产出 `resource/res_diff.json`（入库表）——供 `tool/v5lib.py` 的资源存在性判据与
`script/build/build_rename_map.py` 的冲突面诊断消费。原版发行目录由 `tool.paths`
解析（环境变量 `IFMH_ORIG_DIR` 优先），不再硬编码绝对路径。
"""
import os
import sys
import json
import hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from tool import arcbuild  # noqa: E402
from tool import paths  # noqa: E402

ORIG_DIR = paths.orig_dir()
STEAM_DIR = os.path.join(ROOT, 'backup')
OUT = os.path.join(ROOT, 'resource', 'res_diff.json')

ARCS = ['Rio.arc', 'Script.arc', 'GRAPHIC.arc', 'Chip1.arc', 'CHIP2.arc', 'CHIP3.arc',
        'CHIP4.arc', 'CHIP5.arc', 'CHIP6.arc', 'VOICE.arc', 'SE.arc', 'BGM.arc',
        'Effect.arc', 'SysGraphic.arc', 'SysVoice.arc']


def load(arc_dir, arc):
    p = os.path.join(arc_dir, arc)
    if not os.path.exists(p):
        return None
    out = {}
    for nb, data in arcbuild.read_raw(p):
        try:
            name = nb.decode('utf-16le')
        except Exception:
            name = repr(nb)
        # store (size, sha) lazily: compute sha only when needed -> simpler: compute all
        h = hashlib.sha256(data).hexdigest()
        out[name] = (len(data), h)
    return out


def main():
    res = {}
    for arc in ARCS:
        o = load(ORIG_DIR, arc)
        s = load(STEAM_DIR, arc)
        rec = {'orig_exists': o is not None, 'steam_exists': s is not None}
        if o is not None and s is not None:
            on, sn = set(o), set(s)
            rec['orig_n'] = len(o); rec['steam_n'] = len(sn)
            rec['orig_only'] = sorted(on - sn)
            rec['steam_only'] = sorted(sn - on)
            conflict, same = [], 0
            for n in on & sn:
                if o[n][1] != s[n][1]:
                    conflict.append({'name': n, 'orig_size': o[n][0], 'steam_size': s[n][0]})
                else:
                    same += 1
            rec['same_content'] = same
            rec['conflict'] = conflict
        elif o is not None:
            rec['orig_n'] = len(o)
        elif s is not None:
            rec['steam_n'] = len(s)
        res[arc] = rec
        print(arc, 'done')
    with open(OUT, 'w', encoding='utf-8') as f:
        json.dump(res, f, ensure_ascii=False, indent=1)
    for arc, rec in res.items():
        if not rec.get('orig_exists') or not rec.get('steam_exists'):
            print(arc, 'MISSING ONE SIDE', rec.get('orig_exists'), rec.get('steam_exists'))
            continue
        print('%s: orig=%d steam=%d orig_only=%d steam_only=%d conflict=%d same=%d' % (
            arc, rec['orig_n'], rec['steam_n'], len(rec['orig_only']),
            len(rec['steam_only']), len(rec['conflict']), rec['same_content']))


if __name__ == '__main__':
    main()
