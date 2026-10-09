# -*- coding: utf-8 -*-
"""G3：把原版裸 RIO/SL_*.ws2 从原版引擎编码转换为 Steam 引擎编码。

转换逻辑已提升为公共库 `tool/ws2conv.py`（本体线写盘器共用同一份格式差表
与重定基实现）；本文件只保留 G3 的 CLI：SL 名单 + 输出落点。
"""
import argparse
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BASE))

from tool import scriptext  # noqa: E402
from tool.ws2conv import convert_script  # noqa: E402

OUT_DIR = BASE / 'tmp' / '_l4' / 'asset' / 'RIO'
SL_SCRIPTS = ['SL_KOT_001', 'SL_AGE_001', 'SL_AMA_001', 'SL_HUT_001']


def resolve_orig_dir(cli=None):
    """原版发行目录：--orig-dir 优先，否则取环境变量 IFMH_ORIG_DIR。

    原版素材不进版本库（口径同 tool/scriptext.py 与
    doc/restoration-targets.md §素材来源）。
    """
    d = Path(cli) if cli else scriptext.DEFAULT_ORIG_DIR
    if not d or not Path(d).is_dir():
        sys.exit('原版目录未提供或不存在：传 --orig-dir 或设环境变量 %s'
                 % scriptext.IFMH_ORIG_DIR)
    return Path(d)


def main(orig_dir):
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for name in SL_SCRIPTS:
        src = orig_dir / 'RIO' / (name + '.ws2')
        raw = src.read_bytes()
        out = convert_script(raw, orig_dir)
        dst = OUT_DIR / (name + '.ws2')
        dst.write_bytes(out)
        print('%s: %d -> %d B (+%d) -> %s'
              % (name, len(raw), len(out), len(out) - len(raw), dst))


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description='G3：原版 SL_*.ws2 → Steam 编码')
    ap.add_argument('--orig-dir',
                    help='原版发行目录（含 AdvHD.exe 与裸 RIO/），'
                         '缺省取环境变量 IFMH_ORIG_DIR')
    main(resolve_orig_dir(ap.parse_args().orig_dir))
