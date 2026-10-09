"""路径解析：定位 Steam backup 目录与原版发行目录，并按不区分大小写匹配归档文件名。

路径全部相对本文件推导（本文件在 `tool/` 下），不含任何硬编码绝对路径：
  PATCH = 本仓库根目录（`tool/` 的父目录）
  ROOT  = PATCH 的父目录（原版发行目录与 PATCH 同级）
  STEAM = PATCH/backup（Steam 原始基线，只读）
"""
import os

PATCH = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROOT = os.path.dirname(PATCH)
STEAM = os.path.join(PATCH, 'backup')

_ORIG = None


def orig_dir():
    global _ORIG
    if _ORIG is None:
        # 原版素材不进版本库：优先读环境变量 IFMH_ORIG_DIR
        # （口径同 tool/scriptext.py 与 doc/restoration-targets.md §素材来源）。
        env = os.environ.get('IFMH_ORIG_DIR')
        if env:
            _ORIG = env
        else:
            for d in os.listdir(ROOT):
                # 兼容历史目录名（在这片天空…汉化版）与 2026-10-02 改名后的 If_My_Heart_Had_Wings_Original
                if d.startswith(u'\u5728\u8fd9\u7247\u5929\u7a7a') or d == 'If_My_Heart_Had_Wings_Original':
                    _ORIG = os.path.join(ROOT, d)
                    break
    if _ORIG is None:
        raise RuntimeError('original release dir not found under %s' % ROOT)
    return _ORIG


def listing(dirpath):
    """返回 {小写文件名: 绝对路径}"""
    out = {}
    for fn in os.listdir(dirpath):
        p = os.path.join(dirpath, fn)
        if os.path.isfile(p):
            out[fn.lower()] = p
    return out


TARGETS = [
    'bgm.arc', 'chip1.arc', 'chip2.arc', 'chip3.arc', 'chip4.arc', 'chip5.arc',
    'chip6.arc', 'effect.arc', 'graphic.arc', 'rio.arc', 'se.arc', 'script.arc',
    'sysgraphic.arc', 'sysvoice.arc', 'voice.arc',
]


def match_archives(targets=None):
    """返回 {canonical_key: (orig_path, steam_path)}，只含两边都存在的目标归档。"""
    targets = targets or TARGETS
    o = listing(orig_dir())
    s = listing(STEAM)
    out = {}
    for t in targets:
        if t in o and t in s:
            out[t] = (o[t], s[t])
    return out


def display_name(path):
    return os.path.basename(path)
